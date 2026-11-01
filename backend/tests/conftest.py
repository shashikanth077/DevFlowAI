"""Test fixtures.

The LLM is replaced by a scripted test double that implements the provider
interface; everything else (git, the LangGraph graph, the database, routing,
guards, and - when Docker is available - the sandbox) runs for real.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="devflow-tests-"))
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"sqlite:///{_TMP / 'bootstrap.db'}",
    "CHECKPOINT_BACKEND": "memory",
    "PASSWORD_HASH_ITERATIONS": "1000",
    "WORKSPACE_ROOT": str(_TMP / "workspaces"),
    "LOG_JSON": "false",
    "GITHUB_TOKEN": "",
    "SECRET_KEY": "test-secret-key-for-devflow-ai-unit-tests-only",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database.connection import Base, build_engine, set_engine  # noqa: E402
from app.services.llm_service import LLMConfig, LLMProvider, LLMService  # noqa: E402

get_settings.cache_clear()


class ScriptedProvider(LLMProvider):
    """Deterministic LLM test double keyed by the requested schema's title."""

    name = "scripted"

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = {k: (list(v) if isinstance(v, list) and k.endswith("*") else v) for k, v in responses.items()}
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model, temperature, json_schema):
        title = (json_schema or {}).get("title", "text")
        self.calls.append({"schema": title, "messages": messages, "model": model})
        if f"{title}*" in self.responses:  # sequence of responses, one per call
            queue = self.responses[f"{title}*"]
            response = queue.pop(0) if len(queue) > 1 else queue[0]
        else:
            response = self.responses[title]
        if callable(response):
            response = response(messages)
        import json

        return response if isinstance(response, str) else json.dumps(response)

    def list_models(self) -> list[str]:
        return ["scripted-model"]

    def count(self, title: str) -> int:
        return sum(1 for c in self.calls if c["schema"] == title)


def make_llm(responses: dict[str, Any], **config: Any) -> tuple[LLMService, ScriptedProvider]:
    provider = ScriptedProvider(responses)
    cfg = LLMConfig(provider="ollama", model="scripted-model", max_retries=config.pop("max_retries", 2), **config)
    return LLMService(cfg, provider=provider), provider


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def db_engine(tmp_path: Path):
    """SQLite by default; set TEST_POSTGRES_URL to run the same tests against PostgreSQL."""
    import app.models  # noqa: F401

    url = os.environ.get("TEST_POSTGRES_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    engine = build_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    set_engine(engine)
    yield engine
    if url.startswith("postgresql"):
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_engine) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    client.post("/api/auth/register", json={"email": "dev@example.com", "password": "password123", "full_name": "Dev"})
    token = client.post("/api/auth/login", json={"email": "dev@example.com", "password": "password123"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


SAMPLE_CALC = '''"""Tiny calculator module."""


def add(a: int, b: int) -> int:
    return a + b
'''

SAMPLE_TEST = '''from app.calc import add


def test_add():
    assert add(2, 3) == 5
'''


@pytest.fixture
def remote_repo(tmp_path: Path) -> Callable[..., Path]:
    """Create a bare 'remote' repository seeded with a small Python project."""

    def _make(files: dict[str, str] | None = None) -> Path:
        work = tmp_path / "seed"
        work.mkdir()
        content = files or {
            "README.md": "# Sample service\n",
            "requirements.txt": "pytest\n",
            "app/__init__.py": "",
            "app/calc.py": SAMPLE_CALC,
            "tests/__init__.py": "",
            "tests/test_calc.py": SAMPLE_TEST,
        }
        for rel, text in content.items():
            path = work / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        git(work, "init", "-q", "-b", "main")
        git(work, "add", "-A")
        git(work, "-c", "user.name=t", "-c", "user.email=t@e.com", "commit", "-qm", "initial")
        bare = tmp_path / "remote.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
        return bare

    return _make


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class MemoryRecorder:
    """In-memory WorkflowRecorder for agent-level unit tests."""

    def __init__(self) -> None:
        self.logs: list[tuple[str, str, str | None]] = []
        self.tasks: dict[str, dict] = {}
        self.file_changes: list[dict] = []
        self.tests: list[dict] = []
        self.reviews: list[dict] = []
        self.pull_requests: list[dict] = []
        self.cancel = False
        self.workflow: dict = {}
        self.agents: list[dict] = []
        self.tool_calls: list[dict] = []
        self.trace_runs: list[str] = []

    def log(self, message, *, level="info", agent=None, data=None):
        self.logs.append((level, message, agent))

    def is_cancel_requested(self):
        return self.cancel

    def start_agent(self, agent, node):
        self.agents.append({"agent": agent, "node": node, "status": "running"})
        return str(len(self.agents) - 1)

    def finish_agent(self, execution_id, *, status, output=None, error=None):
        self.agents[int(execution_id)].update(status=status, error=error)

    def update_workflow(self, **fields):
        self.workflow.update(fields)

    def save_tasks(self, tasks):
        for t in tasks:
            if not t.get("__replace__"):
                self.tasks[t["id"]] = t

    def save_file_changes(self, changes):
        self.file_changes = changes

    def approve_file_changes(self, paths):
        pass

    def save_test_result(self, report, attempt):
        self.tests.append(report)

    def save_review(self, report, attempt):
        self.reviews.append(report)

    def save_pull_request(self, data):
        self.pull_requests.append(data)

    def save_tool_call(self, call):
        self.tool_calls.append(call)

    def add_trace_run(self, run_id):
        self.trace_runs.append(run_id)


def make_runtime(llm, tmp_path, *, workflow_id="wf-test", sandbox=None, token=None, github_factory=None, **kw):
    from app.orchestration.runtime import WorkflowRuntime
    from app.services.execution_service import DockerSandbox
    from app.services.github_service import GitHubService
    from app.services.repository_service import RepositoryService

    settings = get_settings().model_copy(update={"workspace_root": tmp_path / "ws", **kw.pop("settings", {})})
    return WorkflowRuntime(
        workflow_id=workflow_id, user_id="u1", settings=settings, llm=llm,
        repositories=RepositoryService(settings), sandbox=sandbox or DockerSandbox(settings),
        recorder=MemoryRecorder(), token_provider=lambda: token,
        github_factory=github_factory or GitHubService, **kw,
    )


class FakeLangSmith:
    """Records the HTTP traffic of a langsmith.Client so tests can assert on the traces it would have sent."""

    def __init__(self) -> None:
        import json as _json

        import requests

        self.requests: list[dict] = []
        outer = self

        class Session(requests.Session):
            def request(self, method, url, **kwargs):  # noqa: D401
                body = kwargs.get("data") if kwargs.get("data") is not None else kwargs.get("json")
                if isinstance(body, (bytes, bytearray)):
                    body = body.decode()
                if isinstance(body, str):
                    try:
                        body = _json.loads(body)
                    except ValueError:
                        pass
                path = "/" + url.split("//", 1)[-1].split("/", 1)[-1]
                outer.requests.append({"method": method, "path": path, "body": body})
                response = requests.Response()
                response.status_code = 200
                payload = body if isinstance(body, dict) else {}
                if method == "GET" and path.startswith("/sessions"):
                    response._content = _json.dumps([{
                        "id": "22222222-2222-2222-2222-222222222222", "name": "devflow-ai",
                        "start_time": "2026-01-01T00:00:00Z", "tenant_id": "33333333-3333-3333-3333-333333333333",
                        "reference_dataset_id": None,
                    }]).encode()
                    response.headers["content-type"] = "application/json"
                    return response
                response._content = _json.dumps({"id": "00000000-0000-0000-0000-000000000000", **payload}).encode()
                response.headers["content-type"] = "application/json"
                return response

        self.session = Session()

    def client_options(self) -> dict:
        return {"session": self.session, "auto_batch_tracing": False, "api_url": "https://langsmith.test",
                "info": {"version": "test", "batch_ingest_config": {}}}

    @property
    def runs(self) -> dict[str, dict]:
        """Final state of every run (create merged with its later update)."""
        merged: dict[str, dict] = {}
        for req in self.requests:
            body = req["body"]
            if req["path"].startswith("/runs") and isinstance(body, dict) and body.get("id"):
                merged.setdefault(body["id"], {}).update(body)
        return merged

    def runs_named(self, prefix: str) -> list[dict]:
        return [r for r in self.runs.values() if str(r.get("name", "")).startswith(prefix)]

    def feedback(self) -> list[dict]:
        return [r["body"] for r in self.requests if r["path"].startswith("/feedback") and isinstance(r["body"], dict)]

    def ancestors(self, run: dict) -> list[str]:
        names: list[str] = []
        runs = self.runs
        while run and run.get("parent_run_id"):
            run = runs.get(str(run["parent_run_id"]))
            if run:
                names.append(run.get("name", ""))
        return names

    def everything_sent(self) -> str:
        import json as _json

        return _json.dumps([r["body"] for r in self.requests], default=str)
