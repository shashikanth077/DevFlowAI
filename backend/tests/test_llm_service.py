import json

import httpx
import pytest
import respx

from app.core.errors import LLMError
from app.schemas.requirement import RequirementAnalysis
from app.services.llm_service import (
    AnthropicProvider,
    LLMConfig,
    LLMProvider,
    LLMService,
    OpenAICompatibleProvider,
    ProviderError,
    extract_json,
)
from tests.conftest import make_llm

VALID = {"title": "Login", "summary": "Add login", "acceptance_criteria": ["user can log in"]}


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Here you go:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('prefix {"a": 3} suffix') == {"a": 3}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_structured_retries_invalid_output_with_feedback():
    llm, provider = make_llm({"RequirementAnalysis*": ["not json", {"summary": "missing title"}, VALID]},
                             max_retries=3)
    result = llm.structured("requirement_analyst", "sys", "user", RequirementAnalysis)
    assert result.title == "Login"
    assert provider.count("RequirementAnalysis") == 3
    # the correction prompt includes the validation error
    assert "invalid" in provider.calls[-1]["messages"][-1]["content"]


def test_structured_gives_up_after_max_retries():
    llm, _ = make_llm({"RequirementAnalysis": "still not json"}, max_retries=2)
    with pytest.raises(LLMError) as exc:
        llm.structured("requirement_analyst", "sys", "user", RequirementAnalysis)
    assert "valid structured output" in exc.value.message


def test_prompts_are_redacted():
    llm, provider = make_llm({"RequirementAnalysis": VALID})
    token = "ghp_" + "b" * 40
    llm.structured("requirement_analyst", "sys", f"token is {token}", RequirementAnalysis)
    sent = json.dumps(provider.calls[0]["messages"])
    assert token not in sent


def test_agent_model_override():
    llm, provider = make_llm({"RequirementAnalysis": VALID}, agent_models={"code_reviewer": "other-model"})
    assert llm.model_for("code_reviewer") == "other-model"
    assert llm.model_for("architect") == "scripted-model"


class FlakyProvider(LLMProvider):
    name = "flaky"

    def __init__(self, errors):
        self.errors = list(errors)

    def list_models(self):
        return []

    def chat(self, messages, *, model, temperature, json_schema):
        if self.errors:
            raise self.errors.pop(0)
        return json.dumps(VALID)


def test_transient_provider_errors_are_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    llm = LLMService(LLMConfig(provider="anthropic", model="m", max_retries=3),
                     provider=FlakyProvider([ProviderError("503", transient=True)]))
    assert llm.structured("a", "s", "u", RequirementAnalysis).title == "Login"


def test_non_transient_provider_error_raises():
    llm = LLMService(LLMConfig(provider="anthropic", model="m", max_retries=3),
                     provider=FlakyProvider([ProviderError("model missing", transient=False)]))
    with pytest.raises(LLMError):
        llm.structured("a", "s", "u", RequirementAnalysis)


@respx.mock
def test_anthropic_provider_uses_messages_api_and_parses():
    route = respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(200, json={
        "content": [{"type": "text", "text": json.dumps(VALID)}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 120, "output_tokens": 40}}))
    llm = LLMService(LLMConfig(provider="anthropic", model="claude-sonnet-5-5", api_key="sk-ant-test"),
                     provider=AnthropicProvider("https://api.anthropic.com", "sk-ant-test", 5, 1024))
    result = llm.structured("requirement_analyst", "sys", "user", RequirementAnalysis)
    assert result.title == "Login"
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "sk-ant-test" and request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 1024
    assert body["system"].startswith("sys") and all(m["role"] != "system" for m in body["messages"])
    assert "RequirementAnalysis" in body["system"]  # the JSON schema is in the instructions


@respx.mock
def test_anthropic_errors_are_clear_and_not_retried():
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(401, json={}))
    provider = AnthropicProvider("https://api.anthropic.com", "bad", 5, 100)
    with pytest.raises(ProviderError) as exc:
        provider.chat([{"role": "user", "content": "x"}], model="m", temperature=0, json_schema=None)
    assert not exc.value.transient and "API key was rejected" in str(exc.value)


def test_anthropic_requires_a_key():
    with pytest.raises(LLMError, match="No Anthropic API key"):
        AnthropicProvider("https://api.anthropic.com", None, 5, 100)


@respx.mock
def test_openai_compatible_provider():
    route = respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(VALID)}}]})
    )
    provider = OpenAICompatibleProvider("openai", "https://api.example.com/v1", "sk-test", 5, "json_schema")
    llm = LLMService(LLMConfig(provider="openai", model="gpt-x"), provider=provider)
    assert llm.structured("a", "s", "u", RequirementAnalysis).title == "Login"
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert json.loads(request.content)["response_format"]["type"] == "json_schema"


def test_openai_provider_requires_key():
    with pytest.raises(LLMError):
        OpenAICompatibleProvider("openai", "https://api.example.com/v1", None, 5, "json_schema")
