"""Policy-enforcing gateway between agents and MCP servers.

Every tool call an agent makes goes through :class:`McpToolBroker`, which enforces:

* **scope**: a server's tools are only visible to the agents its spec allows;
* **read-only by default**: a tool must advertise ``readOnlyHint`` (or be explicitly allow-listed by the
  operator) before a model can call it; destructive or unknown tools are blocked and the attempt is audited;
* **limits**: per-workflow call budget, argument validation against the tool's JSON schema, timeouts;
* **hygiene**: results are redacted for credentials and truncated before they reach a prompt;
* **audit**: every call - allowed, blocked or failed - is persisted and traced in LangSmith.

Servers are connected lazily on first use and closed when the workflow segment ends.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from langsmith import traceable

from app.core.config import Settings
from app.core.security import redact_secrets
from app.mcp_tools.config import McpServerSpec
from app.mcp_tools.connection import McpError, RemoteTool, ServerConnection

logger = logging.getLogger(__name__)


@dataclass
class ToolView:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    allowed: bool
    reason: str = ""

    @property
    def qualified(self) -> str:
        return f"{self.server}.{self.name}"


@dataclass
class ToolOutcome:
    status: str  # ok | error | blocked
    text: str
    duration_ms: int = 0


def evaluate_tool(spec: McpServerSpec, tool: RemoteTool) -> tuple[bool, str]:
    """Decide whether a model may call ``tool``. Returns ``(allowed, reason)``."""
    if tool.name in spec.tools_deny:
        return False, "denied by operator policy"
    if tool.name in spec.tools_allow:
        return True, "allow-listed by operator"
    if tool.destructive and not spec.allow_write_tools:
        return False, "marked destructive"
    if tool.read_only:
        return True, "read-only"
    if spec.allow_write_tools:
        return True, "write tools enabled for this server"
    return False, "not marked read-only (set tools_allow or allow_write_tools to permit)"


def _trace_inputs(inputs: dict) -> dict:
    return {"server": inputs.get("server"), "tool": inputs.get("tool"), "arguments": inputs.get("arguments")}


@traceable(run_type="tool", name="mcp.call_tool", process_inputs=_trace_inputs)
def _traced_call(conn: ServerConnection, server: str, tool: str, arguments: dict, timeout: float) -> dict[str, Any]:
    raw = conn.call_tool(tool, arguments, timeout=timeout)
    return {"is_error": raw.is_error, "text": raw.text, "non_text_blocks": raw.non_text_blocks}


class McpToolBroker:
    def __init__(self, specs: list[McpServerSpec], settings: Settings, recorder: Any, *,
                 disabled_servers: set[str] | None = None) -> None:
        disabled = disabled_servers or set()
        self.specs = {s.name: s for s in specs if s.name not in disabled}
        self.settings = settings
        self.recorder = recorder
        self._conns: dict[str, ServerConnection] = {}
        self._tools: dict[str, list[ToolView]] = {}
        self._failed: dict[str, str] = {}
        self._lock = threading.RLock()
        self._calls = 0
        self.connect_errors: dict[str, str] = {}

    # -- connections ----------------------------------------------------------------------------

    def _connection(self, spec: McpServerSpec) -> ServerConnection | None:
        with self._lock:
            if spec.name in self._failed:
                return None
            conn = self._conns.get(spec.name)
            if conn is not None:
                return conn
            conn = ServerConnection(spec, connect_timeout=self.settings.mcp_connect_timeout_seconds)
            try:
                conn.start()
                tools = conn.list_tools(timeout=self.settings.mcp_connect_timeout_seconds)
            except McpError as exc:
                self._failed[spec.name] = exc.message
                self.connect_errors[spec.name] = exc.message
                logger.warning("MCP server unavailable", extra={"server": spec.name, "error": exc.message})
                self.recorder.log(f"MCP server '{spec.name}' unavailable: {exc.message}", level="warning")
                return None
            views = []
            for tool in tools:
                allowed, reason = evaluate_tool(spec, tool)
                views.append(ToolView(spec.name, tool.name, tool.description, tool.input_schema, tool.read_only,
                                      allowed, reason))
            self._conns[spec.name] = conn
            self._tools[spec.name] = views
            return conn

    def catalog(self, agent: str) -> list[ToolView]:
        """Tools this agent may call (blocked tools are never shown to the model)."""
        out: list[ToolView] = []
        for spec in self.specs.values():
            if not spec.allowed_for(agent):
                continue
            if self._connection(spec) is None:
                continue
            out.extend(t for t in self._tools[spec.name] if t.allowed)
        return out

    def discover(self, spec: McpServerSpec) -> list[ToolView]:
        """All tools of a server including blocked ones (for the Settings diagnostics screen)."""
        if self._connection(spec) is None:
            raise McpError(self._failed.get(spec.name, "connection failed"))
        return list(self._tools[spec.name])

    # -- calls ------------------------------------------------------------------------------------

    def call(self, agent: str, server: str, tool: str, arguments: dict[str, Any] | None) -> ToolOutcome:
        arguments = arguments or {}
        started = time.monotonic()

        def finish(status: str, text: str) -> ToolOutcome:
            outcome = ToolOutcome(status, text, int((time.monotonic() - started) * 1000))
            try:
                self.recorder.save_tool_call({
                    "agent": agent, "server": server, "tool": tool, "arguments": _preview_args(arguments),
                    "status": status, "result_preview": text[:1500], "duration_ms": outcome.duration_ms,
                })
                self.recorder.log(f"MCP {server}.{tool} -> {status} ({outcome.duration_ms} ms)", agent=agent,
                                  level="info" if status == "ok" else "warning")
            except Exception:  # noqa: BLE001 - auditing must never take the workflow down
                logger.exception("Could not record MCP tool call")
            return outcome

        spec = self.specs.get(server)
        if spec is None or not spec.allowed_for(agent):
            return finish("blocked", f"Server '{server}' is not available to {agent}.")
        with self._lock:
            if self._calls >= self.settings.mcp_max_calls_per_workflow:
                return finish("blocked", "The tool call budget for this workflow is exhausted.")
            self._calls += 1
        conn = self._connection(spec)
        if conn is None:
            return finish("error", f"MCP server '{server}' is unavailable: {self._failed.get(server)}")
        view = next((t for t in self._tools[server] if t.name == tool), None)
        if view is None:
            return finish("error", f"Unknown tool '{tool}' on server '{server}'.")
        if not view.allowed:
            return finish("blocked", f"Tool '{tool}' is blocked by policy: {view.reason}.")
        problems = sorted(e.message for e in Draft202012Validator(view.input_schema).iter_errors(arguments))[:3]
        if problems:
            return finish("error", "Invalid arguments: " + "; ".join(problems))
        try:
            result = _traced_call(
                conn, server, tool, arguments, self.settings.mcp_tool_timeout_seconds,
                langsmith_extra={"name": f"mcp:{server}.{tool}", "tags": ["mcp", agent],
                                 "metadata": {"agent": agent, "mcp_server": server, "mcp_tool": tool}},
            )
        except McpError as exc:
            return finish("error", exc.message)
        text = redact_secrets(result["text"])
        limit = self.settings.mcp_result_max_chars
        if len(text) > limit:
            text = text[:limit] + f"\n... [truncated {len(text) - limit} characters]"
        if result["non_text_blocks"]:
            text += f"\n[{result['non_text_blocks']} non-text content block(s) omitted]"
        return finish("error" if result["is_error"] else "ok", text or "(empty result)")

    def close(self) -> None:
        with self._lock:
            conns, self._conns = list(self._conns.values()), {}
        for conn in conns:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                logger.warning("Error closing MCP connection", exc_info=True)


def _preview_args(arguments: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        text = value if isinstance(value, str) else repr(value)
        out[str(key)] = redact_secrets(text)[:300] if isinstance(value, str) else value
    return out
