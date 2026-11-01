import json

import httpx
import respx

from app.core.config import get_settings
from app.observability.tracing import Tracing, configure_tracing, sanitize_payload
from app.services.llm_service import LLMConfig, LLMService
from tests.conftest import FakeLangSmith

TOKEN = "ghp_" + "a" * 36


def test_sanitize_redacts_truncates_and_hides():
    payload = {"messages": [{"role": "user", "content": f"token {TOKEN} " + "x" * 50}], "n": 3, "ok": True}
    clean = sanitize_payload(payload, max_chars=30)
    text = json.dumps(clean)
    assert TOKEN not in text and "[REDACTED GITHUB TOKEN]" in text and "truncated" in text
    assert clean["n"] == 3 and clean["ok"] is True
    hidden = sanitize_payload(payload, hide_content=True)
    assert hidden["messages"][0]["content"].startswith("[hidden:") and hidden["n"] == 3
    assert sanitize_payload({"o": object()})["o"].startswith("<object")


def test_status_never_exposes_the_api_key():
    settings = get_settings().model_copy(update={"langsmith_api_key": "lsv2_secret_key", "langsmith_tracing": True})
    status = Tracing(settings).status()
    assert status["enabled"] and status["api_key_configured"] and status["project"] == "devflow-ai"
    assert "lsv2_secret_key" not in json.dumps(status)


def test_disabled_without_key_or_flag():
    base = get_settings()
    assert not Tracing(base.model_copy(update={"langsmith_tracing": True, "langsmith_api_key": None})).enabled
    assert not Tracing(base.model_copy(update={"langsmith_tracing": False, "langsmith_api_key": "k"})).enabled
    config, run_id = Tracing(base).run_config({"a": 1}, workflow_id="w", metadata={})
    assert config == {"a": 1} and run_id is None


def test_configure_tracing_turns_off_global_env_tracing(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    configure_tracing(get_settings())
    import os

    assert os.environ["LANGSMITH_TRACING"] == "false" and os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_standard_langsmith_env_names_are_honoured(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_x")
    monkeypatch.setenv("LANGSMITH_PROJECT", "my-project")
    s = Settings()
    assert s.langsmith_tracing and s.langsmith_api_key == "lsv2_x" and s.langsmith_project == "my-project"


def test_llm_call_is_traced_with_usage_and_redaction():
    fake = FakeLangSmith()
    settings = get_settings().model_copy(update={"langsmith_tracing": True, "langsmith_api_key": "k"})
    tracing = Tracing(settings, client_options=fake.client_options())
    config, run_id = tracing.run_config({}, workflow_id="wf-1", metadata={"repository": "acme/calc"}, tags=["t"])
    assert run_id

    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    from app.schemas.requirement import RequirementAnalysis

    class S(TypedDict, total=False):
        x: str

    with respx.mock:
        respx.post("http://ollama.test/api/chat").mock(return_value=httpx.Response(200, json={
            "message": {"content": json.dumps({"title": "T", "summary": "S"})},
            "prompt_eval_count": 120, "eval_count": 30}))
        llm = LLMService(LLMConfig(provider="ollama", model="llama3.1:8b", base_url="http://ollama.test"))

        def node(state):
            llm.structured("architect", "system", f"user text with {TOKEN}", RequirementAnalysis)
            return {"x": "done"}

        graph = StateGraph(S)
        graph.add_node("architect_node", node)
        graph.add_edge(START, "architect_node")
        graph.add_edge("architect_node", END)
        graph.compile().invoke({"x": "a"}, config)
    tracing.flush()

    root = fake.runs[run_id]
    assert root["name"] == "devflow-workflow" and root["extra"]["metadata"]["repository"] == "acme/calc"
    assert root["extra"]["metadata"]["thread_id"] == "wf-1" and "devflow" in root["tags"]
    llm_run = fake.runs_named("llm:architect")[0]
    assert llm_run["run_type"] == "llm" and llm_run["extra"]["metadata"]["ls_model_name"] == "llama3.1:8b"
    assert llm_run["outputs"]["usage_metadata"] == {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
    assert fake.ancestors(llm_run) == ["architect_node", "devflow-workflow"]  # nested under its graph node
    assert TOKEN not in fake.everything_sent()  # credentials never leave the process


def test_hide_content_sends_structure_only():
    fake = FakeLangSmith()
    settings = get_settings().model_copy(update={"langsmith_tracing": True, "langsmith_api_key": "k",
                                                 "langsmith_hide_content": True})
    tracing = Tracing(settings, client_options=fake.client_options())
    config, run_id = tracing.run_config({}, workflow_id="wf-2", metadata={})
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class S(TypedDict, total=False):
        secret_requirement: str

    g = StateGraph(S)
    g.add_node("n", lambda s: {"secret_requirement": "customer data here"})
    g.add_edge(START, "n")
    g.add_edge("n", END)
    g.compile().invoke({"secret_requirement": "proprietary algorithm details"}, config)
    tracing.flush()
    sent = fake.everything_sent()
    assert "proprietary algorithm" not in sent and "customer data" not in sent and "[hidden:" in sent


def test_feedback_and_failures_are_best_effort():
    fake = FakeLangSmith()
    settings = get_settings().model_copy(update={"langsmith_tracing": True, "langsmith_api_key": "k"})
    tracing = Tracing(settings, client_options=fake.client_options())
    tracing.feedback("11111111-1111-1111-1111-111111111111", "human_approval_release", 1.0, f"ok {TOKEN}")
    sent = fake.feedback()
    assert sent and sent[0]["key"] == "human_approval_release" and sent[0]["score"] == 1.0
    assert sent[0]["session_id"] == "22222222-2222-2222-2222-222222222222"  # project resolved once
    assert sent[0]["trace_id"] == "11111111-1111-1111-1111-111111111111"
    assert TOKEN not in json.dumps(sent)
    tracing.feedback(None, "ignored", 1.0)  # no run id -> no-op, no exception
    broken = Tracing(settings, client=object())  # client without the expected API -> logged, not raised
    broken.feedback("x", "k", 1.0)
    assert broken.run_url("x") is None
    assert Tracing(get_settings()).check_connection()["ok"] is False
