import json

import httpx
import pytest
import respx

from app.core.errors import LLMError
from app.schemas.requirement import RequirementAnalysis
from app.services.llm_service import (
    LLMConfig,
    LLMService,
    OllamaProvider,
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


class FlakyProvider(OllamaProvider):
    def __init__(self, errors):
        self.errors = list(errors)
        self.name = "flaky"

    def chat(self, messages, *, model, temperature, json_schema):
        if self.errors:
            raise self.errors.pop(0)
        return json.dumps(VALID)


def test_transient_provider_errors_are_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    llm = LLMService(LLMConfig(provider="ollama", model="m", max_retries=3),
                     provider=FlakyProvider([ProviderError("503", transient=True)]))
    assert llm.structured("a", "s", "u", RequirementAnalysis).title == "Login"


def test_non_transient_provider_error_raises():
    llm = LLMService(LLMConfig(provider="ollama", model="m", max_retries=3),
                     provider=FlakyProvider([ProviderError("model missing", transient=False)]))
    with pytest.raises(LLMError):
        llm.structured("a", "s", "u", RequirementAnalysis)


@respx.mock
def test_ollama_provider_sends_schema_and_parses():
    route = respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(VALID)}})
    )
    llm = LLMService(LLMConfig(provider="ollama", model="llama3.1:8b", base_url="http://ollama:11434"))
    result = llm.structured("requirement_analyst", "sys", "user", RequirementAnalysis)
    assert result.title == "Login"
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "llama3.1:8b"
    assert body["format"]["title"] == "RequirementAnalysis"
    assert body["stream"] is False


@respx.mock
def test_ollama_missing_model_is_not_retried():
    respx.post("http://ollama:11434/api/chat").mock(
        return_value=httpx.Response(404, json={"error": "model 'x' not found"})
    )
    provider = OllamaProvider("http://ollama:11434", 5)
    with pytest.raises(ProviderError) as exc:
        provider.chat([], model="x", temperature=0, json_schema=None)
    assert not exc.value.transient and "ollama pull x" in str(exc.value)


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
