"""Provider-independent LLM access with validated structured output.

Agents never talk to a provider directly. They call :class:`LLMService`, which

* selects the configured provider (Ollama by default, OpenAI/Mistral via the
  OpenAI-compatible chat completions API),
* resolves the model per agent (agents can be pinned to different models),
* redacts secrets from every prompt,
* requests JSON output constrained by the Pydantic schema,
* validates the response and asks the model to correct invalid output, and
* retries transient provider failures with exponential backoff.
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from langsmith import traceable
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import LLMError
from app.core.security import redact_secrets

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMConfig:
    provider: str
    model: str
    temperature: float = 0.2
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    timeout_seconds: float = 300.0
    max_retries: int = 3
    agent_models: dict[str, str] = field(default_factory=dict)
    context_chars: int = 60_000

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **overrides: Any) -> LLMConfig:
        s = settings or get_settings()
        cfg = cls(
            provider=s.llm_provider,
            model=s.llm_model,
            temperature=s.llm_temperature,
            timeout_seconds=s.llm_timeout_seconds,
            max_retries=s.llm_max_retries,
            context_chars=s.llm_context_chars,
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(cfg, key, value)
        return cfg


class ProviderError(Exception):
    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass
class ChatResponse:
    content: str
    usage: dict[str, int] | None = None  # input_tokens / output_tokens / total_tokens


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def chat(
        self, messages: list[dict[str, str]], *, model: str, temperature: float, json_schema: dict | None
    ) -> str:
        """Return the assistant message content."""

    def chat_full(
        self, messages: list[dict[str, str]], *, model: str, temperature: float, json_schema: dict | None
    ) -> ChatResponse:
        """Like :meth:`chat` but also reports token usage when the provider exposes it."""
        return ChatResponse(self.chat(messages, model=model, temperature=temperature, json_schema=json_schema))

    @abstractmethod
    def list_models(self) -> list[str]: ...


def _raise_for_status(response: httpx.Response, provider: str) -> None:
    if response.status_code < 400:
        return
    transient = response.status_code in (408, 409, 425, 429) or response.status_code >= 500
    body = response.text[:500]
    raise ProviderError(f"{provider} returned HTTP {response.status_code}: {body}", transient=transient)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, timeout: float) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def chat(self, messages, *, model, temperature, json_schema):
        return self.chat_full(messages, model=model, temperature=temperature, json_schema=json_schema).content

    def chat_full(self, messages, *, model, temperature, json_schema):
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_schema is not None:
            payload["format"] = json_schema  # Ollama >= 0.5 supports JSON-schema constrained output
        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.TransportError as exc:
            raise ProviderError(f"Cannot reach Ollama at {self._client.base_url}: {exc}", transient=True) from exc
        if response.status_code == 404 and "not found" in response.text.lower():
            raise ProviderError(
                f"Model '{model}' is not available in Ollama. Run: ollama pull {model}", transient=False
            )
        _raise_for_status(response, "Ollama")
        body = response.json()
        usage = None
        if "prompt_eval_count" in body or "eval_count" in body:
            inp, out = int(body.get("prompt_eval_count", 0)), int(body.get("eval_count", 0))
            usage = {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
        return ChatResponse(body.get("message", {}).get("content", ""), usage)

    def list_models(self) -> list[str]:
        try:
            response = self._client.get("/api/tags")
        except httpx.TransportError as exc:
            raise ProviderError(f"Cannot reach Ollama: {exc}", transient=True) from exc
        _raise_for_status(response, "Ollama")
        return [m.get("name", "") for m in response.json().get("models", [])]


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI chat-completions API; also used for Mistral (same wire format)."""

    def __init__(self, name: str, base_url: str, api_key: str | None, timeout: float, structured_mode: str) -> None:
        if not api_key:
            raise LLMError(f"No API key configured for provider '{name}'.")
        self.name = name
        self._structured_mode = structured_mode
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )

    def chat(self, messages, *, model, temperature, json_schema):
        return self.chat_full(messages, model=model, temperature=temperature, json_schema=json_schema).content

    def chat_full(self, messages, *, model, temperature, json_schema):
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if json_schema is not None:
            if self._structured_mode == "json_schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": json_schema},
                }
            else:
                payload["response_format"] = {"type": "json_object"}
        try:
            response = self._client.post("/chat/completions", json=payload)
        except httpx.TransportError as exc:
            raise ProviderError(f"Cannot reach {self.name}: {exc}", transient=True) from exc
        _raise_for_status(response, self.name)
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.name} returned no choices", transient=True)
        raw_usage = body.get("usage") or {}
        usage = None
        if raw_usage:
            inp, out = int(raw_usage.get("prompt_tokens", 0)), int(raw_usage.get("completion_tokens", 0))
            usage = {"input_tokens": inp, "output_tokens": out, "total_tokens": int(raw_usage.get("total_tokens", inp + out))}
        return ChatResponse(choices[0].get("message", {}).get("content") or "", usage)

    def list_models(self) -> list[str]:
        try:
            response = self._client.get("/models")
        except httpx.TransportError as exc:
            raise ProviderError(f"Cannot reach {self.name}: {exc}", transient=True) from exc
        _raise_for_status(response, self.name)
        return [m.get("id", "") for m in response.json().get("data", [])]


def build_provider(config: LLMConfig, settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    if config.provider == "ollama":
        return OllamaProvider(config.base_url or s.ollama_base_url, config.timeout_seconds)
    if config.provider == "openai":
        return OpenAICompatibleProvider(
            "openai", config.base_url or s.openai_base_url, config.api_key or s.openai_api_key,
            config.timeout_seconds, "json_schema",
        )
    if config.provider == "mistral":
        return OpenAICompatibleProvider(
            "mistral", config.base_url or s.mistral_base_url, config.api_key or s.mistral_api_key,
            config.timeout_seconds, "json_object",
        )
    raise LLMError(f"Unsupported LLM provider '{config.provider}'")


def _trace_inputs(inputs: dict) -> dict:
    return {"messages": inputs.get("messages"), "model": inputs.get("model"),
            "temperature": inputs.get("temperature"), "structured_output": inputs.get("json_schema") is not None}


@traceable(run_type="llm", name="llm.chat", process_inputs=_trace_inputs)
def _traced_chat(provider: LLMProvider, messages: list, model: str, temperature: float,
                 json_schema: dict | None) -> dict[str, Any]:
    """One provider call. A no-op wrapper unless a LangSmith run is active (see app/observability)."""
    response = provider.chat_full(messages, model=model, temperature=temperature, json_schema=json_schema)
    out: dict[str, Any] = {"content": response.content}
    if response.usage:
        out["usage_metadata"] = response.usage
    return out


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating code fences and surrounding prose."""
    text = text.strip()
    candidates = [text]
    candidates += [m.group(1).strip() for m in _FENCE_RE.finditer(text)]
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise ValueError(f"Response is not valid JSON: {last_error}")


@dataclass
class LLMCallRecord:
    agent: str
    model: str
    attempts: int
    duration_ms: int
    ok: bool


class LLMService:
    def __init__(self, config: LLMConfig, provider: LLMProvider | None = None) -> None:
        self.config = config
        self.provider = provider or build_provider(config)
        self.calls: list[LLMCallRecord] = []

    def model_for(self, agent: str) -> str:
        return self.config.agent_models.get(agent) or self.config.model

    def truncate(self, text: str, limit: int | None = None) -> str:
        limit = limit or self.config.context_chars
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n... [truncated {len(text) - limit} characters]"

    def _chat_with_retry(self, agent: str, messages: list[dict[str, str]], schema: dict | None) -> str:
        model = self.model_for(agent)
        delay = 1.0
        for attempt in range(1, self.config.max_retries + 1):
            try:
                result = _traced_chat(
                    self.provider, messages, model, self.config.temperature, schema,
                    langsmith_extra={
                        "name": f"llm:{agent}",
                        "tags": [agent],
                        "metadata": {"agent": agent, "ls_provider": self.provider.name, "ls_model_name": model,
                                     "ls_temperature": self.config.temperature, "attempt": attempt},
                    },
                )
                return result["content"]
            except ProviderError as exc:
                logger.warning(
                    "LLM provider error", extra={"agent": agent, "attempt": attempt, "error": str(exc)}
                )
                if not exc.transient or attempt == self.config.max_retries:
                    raise LLMError(str(exc), details={"provider": self.provider.name, "model": model}) from exc
                time.sleep(delay)
                delay = min(delay * 2, 30)
        raise LLMError("LLM call failed")  # pragma: no cover - loop always returns or raises

    def structured(self, agent: str, system: str, user: str, schema: type[T]) -> T:
        """Ask the model for JSON matching ``schema`` and return the validated object."""
        json_schema = schema.model_json_schema()
        instructions = (
            "Respond ONLY with a single JSON object that conforms to this JSON schema. "
            "Do not wrap it in markdown and do not add commentary.\n"
            f"JSON schema:\n{json.dumps(json_schema)}"
        )
        messages = [
            {"role": "system", "content": redact_secrets(f"{system}\n\n{instructions}")},
            {"role": "user", "content": redact_secrets(user)},
        ]
        started = time.monotonic()
        last_error = ""
        for attempt in range(1, self.config.max_retries + 1):
            raw = self._chat_with_retry(agent, messages, json_schema)
            try:
                result = schema.model_validate(extract_json(raw))
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:2000]
                logger.info("LLM output failed validation", extra={"agent": agent, "attempt": attempt})
                messages = messages + [
                    {"role": "assistant", "content": raw[:8000]},
                    {
                        "role": "user",
                        "content": "Your previous response was invalid: "
                        f"{last_error}\nReturn ONLY corrected JSON that matches the schema.",
                    },
                ]
                continue
            self._record(agent, attempt, started, ok=True)
            return result
        self._record(agent, self.config.max_retries, started, ok=False)
        raise LLMError(
            f"{agent}: model did not produce valid structured output after {self.config.max_retries} attempts",
            details={"validation_error": last_error, "model": self.model_for(agent)},
        )

    def text(self, agent: str, system: str, user: str) -> str:
        started = time.monotonic()
        messages = [
            {"role": "system", "content": redact_secrets(system)},
            {"role": "user", "content": redact_secrets(user)},
        ]
        result = self._chat_with_retry(agent, messages, None)
        self._record(agent, 1, started, ok=True)
        return result

    def _record(self, agent: str, attempts: int, started: float, *, ok: bool) -> None:
        record = LLMCallRecord(agent, self.model_for(agent), attempts, int((time.monotonic() - started) * 1000), ok)
        self.calls.append(record)
        logger.info("LLM call", extra=record.__dict__)
