"""LangSmith observability for workflows, LLM calls and MCP tool calls.

Design:

* One explicit :class:`langsmith.Client` is used for *every* trace. It carries
  ``hide_inputs``/``hide_outputs`` hooks that redact credentials (and optionally hide
  all content) before anything leaves this process.
* The library's global env-based tracing is switched off at startup, so a stray
  ``LANGSMITH_TRACING=true`` in the environment cannot create unredacted duplicate traces.
* Each graph invocation (the initial run and every resume after an approval) becomes one
  root run whose id we choose, so it can be stored on the workflow and linked from the
  dashboard. All segments of a workflow share ``thread_id`` metadata, which LangSmith
  groups into one thread.
* Tracing never breaks a workflow: every call into LangSmith is guarded.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from typing import Any

from app.core.config import Settings, get_settings
from app.core.security import redact_secrets

logger = logging.getLogger(__name__)

_JSONScalar = (int, float, bool, type(None))


def sanitize_payload(obj: Any, *, hide_content: bool = False, max_chars: int = 20_000, _depth: int = 0) -> Any:
    """Return a copy of ``obj`` that is safe to send to a third-party service.

    Strings are scrubbed of credentials and truncated; with ``hide_content`` every string is
    replaced by a length marker so only the shape of the data is visible.
    """
    if _depth > 12:
        return "[max depth]"
    if isinstance(obj, str):
        if hide_content:
            return f"[hidden: {len(obj)} chars]"
        text = redact_secrets(obj)
        if len(text) > max_chars:
            text = text[:max_chars] + f"... [truncated {len(obj) - max_chars} chars]"
        return text
    if isinstance(obj, _JSONScalar):
        return obj
    if isinstance(obj, dict):
        return {
            str(k): sanitize_payload(v, hide_content=hide_content, max_chars=max_chars, _depth=_depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_payload(v, hide_content=hide_content, max_chars=max_chars, _depth=_depth + 1) for v in obj]
    return sanitize_payload(str(obj), hide_content=hide_content, max_chars=max_chars, _depth=_depth + 1)


class Tracing:
    """Facade over the LangSmith client used by the workflow runner and the LLM/MCP layers."""

    def __init__(self, settings: Settings | None = None, client: Any = None,
                 client_options: dict[str, Any] | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._client_options = client_options or {}
        self._project_id: str | None = None
        self._project_lookup_failed = False
        self._lock = threading.Lock()

    # -- state -------------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self._client is not None or self.settings.langsmith_api_key)

    @property
    def enabled(self) -> bool:
        return bool(self._client is not None or (self.settings.langsmith_tracing and self.configured))

    @property
    def project(self) -> str:
        return self.settings.langsmith_project

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "api_key_configured": self.configured,
            "project": self.project,
            "endpoint": self.settings.langsmith_endpoint,
            "hide_content": self.settings.langsmith_hide_content,
            "redaction": "all content hidden" if self.settings.langsmith_hide_content else "credentials redacted",
        }

    def _sanitize(self, payload: dict) -> dict:
        try:
            return sanitize_payload(
                payload,
                hide_content=self.settings.langsmith_hide_content,
                max_chars=self.settings.langsmith_max_field_chars,
            )
        except Exception:  # noqa: BLE001 - never leak an unsanitised payload because redaction failed
            logger.exception("Trace redaction failed; dropping payload")
            return {"redaction_error": True}

    @property
    def client(self) -> Any:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from langsmith import Client

                    options: dict[str, Any] = {
                        "api_url": self.settings.langsmith_endpoint,
                        "api_key": self.settings.langsmith_api_key,
                        "hide_inputs": self._sanitize,
                        "hide_outputs": self._sanitize,
                        "tracing_error_callback": lambda exc: logger.warning("LangSmith tracing error: %s", exc),
                    }
                    options.update(self._client_options)
                    self._client = Client(**options)
        return self._client

    # -- workflow runs --------------------------------------------------------------------

    def run_config(
        self, config: dict[str, Any], *, workflow_id: str, metadata: dict[str, Any], tags: list[str] | None = None,
        resumed: bool = False,
    ) -> tuple[dict[str, Any], str | None]:
        """Return ``(config, root_run_id)`` with a LangSmith tracer attached (or unchanged if disabled)."""
        if not self.enabled:
            return config, None
        try:
            from langchain_core.tracers.langchain import LangChainTracer

            run_id = uuid.uuid4()
            tracer = LangChainTracer(client=self.client, project_name=self.project)
            traced = {
                **config,
                "callbacks": [*config.get("callbacks", []), tracer],
                "run_id": run_id,
                "run_name": "devflow-workflow" + ("-resume" if resumed else ""),
                "tags": ["devflow", *(tags or [])],
                "metadata": {**metadata, "workflow_id": workflow_id, "thread_id": workflow_id, "resumed": resumed},
            }
            return traced, str(run_id)
        except Exception:  # noqa: BLE001
            logger.exception("Could not attach LangSmith tracer; continuing without tracing")
            return config, None

    def feedback(self, run_id: str | None, key: str, score: float | None, comment: str | None = None,
                 value: Any = None) -> None:
        """Attach an evaluation signal (approval, outcome, ...) to a trace. Best effort."""
        if not (self.enabled and run_id):
            return
        try:
            self.client.create_feedback(
                run_id=run_id, key=key, score=score, value=value, trace_id=run_id,
                session_id=self._session_id(),
                comment=sanitize_payload(comment, max_chars=500) if comment else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record LangSmith feedback '%s': %s", key, exc)

    def _session_id(self) -> str | None:
        """The LangSmith project (session) id; LangSmith requires it on feedback. Cached; best effort."""
        if self._project_id or self._project_lookup_failed:
            return self._project_id
        try:
            self._project_id = str(self.client.read_project(project_name=self.project).id)
        except Exception as exc:  # noqa: BLE001
            self._project_lookup_failed = True
            logger.info("Could not resolve LangSmith project id (%s); feedback sent without it", exc)
        return self._project_id

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LangSmith flush failed: %s", exc)

    def run_url(self, run_id: str) -> str | None:
        """Best-effort deep link to a trace (requires a round trip to LangSmith)."""
        if not self.enabled:
            return None
        try:
            run = self.client.read_run(run_id)
            return self.client.get_run_url(run=run, project_name=self.project)
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not resolve LangSmith run URL: %s", exc)
            return None

    def check_connection(self) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "message": "LANGSMITH_API_KEY is not set."}
        try:
            next(iter(self.client.list_projects(limit=1)), None)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Cannot reach LangSmith: {str(exc)[:300]}"}
        state = "enabled" if self.enabled else "reachable, but tracing is disabled (set LANGSMITH_TRACING=true)"
        return {"ok": True, "message": f"Connected to LangSmith; project '{self.project}' - tracing {state}."}


_tracing: Tracing | None = None


def get_tracing() -> Tracing:
    global _tracing
    if _tracing is None:
        _tracing = Tracing(get_settings())
    return _tracing


def set_tracing(tracing: Tracing | None) -> None:
    global _tracing
    _tracing = tracing


def configure_tracing(settings: Settings | None = None) -> Tracing:
    """Disable the library's global env tracing and (re)create the tracing facade."""
    for var in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING"):
        os.environ[var] = "false"
    tracing = Tracing(settings or get_settings())
    set_tracing(tracing)
    if tracing.enabled:
        logger.info("LangSmith tracing enabled", extra={"project": tracing.project,
                                                         "hide_content": tracing.settings.langsmith_hide_content})
    return tracing
