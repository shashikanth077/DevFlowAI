"""End-to-end LangGraph workflow tests through the REST API.

Real: FastAPI, SQLite DB, LangGraph graph + checkpointer, git clone/commit/push
(to a local bare repository standing in for GitHub), routing, retries and
approval gates. Test doubles: the LLM (scripted), the GitHub REST API (httpx
mock transport) and - unless Docker is available - the sandbox.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from app.core.config import get_settings
from app.database.session import session_scope
from app.models import GitHubRepository, User, WorkflowExecution
from app.services.github_service import GitHubService
from app.services.workflow_service import DBRecorder, WorkflowManager, set_workflow_manager
from tests.conftest import SAMPLE_CALC, SAMPLE_TEST, docker_available, git, make_llm, make_runtime
from tests.test_agents import FakeSandbox

BUGGY = SAMPLE_CALC + "\n\ndef subtract(a: int, b: int) -> int:\n    return a + b\n"
FIXED = SAMPLE_CALC + "\n\ndef subtract(a: int, b: int) -> int:\n    return a - b\n"
NEW_TEST = SAMPLE_TEST.replace("from app.calc import add", "from app.calc import add, subtract") + (
    "\n\ndef test_subtract():\n    assert subtract(5, 3) == 2\n"
)


def llm_script():
    return {
        "RequirementAnalysis": {
            "title": "Add subtract function", "summary": "Provide subtraction in the calculator module.",
            "business_objectives": ["Support subtraction"],
            "functional_requirements": [{"id": "FR-1", "description": "subtract(a, b) returns a - b"}],
            "acceptance_criteria": ["subtract(5, 3) == 2"], "ambiguities": ["Should floats be supported?"],
            "proposed_tasks": [{"title": "Implement subtract", "area": "backend"}],
        },
        "RepositoryInsights": {
            "architecture_summary": "Single Python package with pytest tests.",
            "conventions": ["type hints", "tests in tests/"],
            "relevant_files": [{"path": "app/calc.py", "action": "modify"},
                               {"path": "tests/test_calc.py", "action": "modify"},
                               {"path": "does/not/exist.py", "action": "reference"}],
        },
        "ArchitecturePlan": {
            "approach": "Add a pure function next to add().",
            "backend_changes": ["add subtract()"],
            "file_plan": [{"path": "app/calc.py", "action": "modify", "area": "backend"},
                          {"path": "tests/test_calc.py", "action": "modify", "area": "backend"}],
            "testing_strategy": ["unit test"],
        },
        "TaskPlan": {"tasks": [{"id": "T1", "title": "Implement subtract", "assigned_agent": "backend",
                                "target_files": ["app/calc.py", "tests/test_calc.py"]}]},
        "CodeChangeSet*": [
            {"summary": "Add subtract", "changes": [
                {"path": "app/calc.py", "action": "modify", "content": BUGGY},
                {"path": "tests/test_calc.py", "action": "modify", "content": NEW_TEST}]},
            {"summary": "Fix subtract sign", "changes": [
                {"path": "app/calc.py", "action": "modify", "content": FIXED}]},
        ],
        "FailureAnalysis": {"failures": [{"command": "python -m pytest -q", "summary": "subtract returns a+b",
                                          "files": ["app/calc.py"], "responsible_agent": "backend",
                                          "suggested_fix": "use a - b"}]},
        "LLMReview": {"approved": True, "summary": "Correct and tested.", "issues": []},
    }


class FakeGitHub:
    def __init__(self):
        self.created: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ghp_testtoken"
        if request.method == "GET" and "/branches/" in request.url.path:
            return httpx.Response(404, json={"message": "Branch not found"})
        if request.method == "POST" and request.url.path.endswith("/pulls"):
            body = json.loads(request.content)
            self.created.append(body)
            return httpx.Response(201, json={"number": 7, "html_url": "https://github.com/acme/calc/pull/7",
                                             "title": body["title"], "state": "open", "draft": body["draft"]})
        return httpx.Response(500, json={"message": f"unexpected {request.method} {request.url}"})

    def factory(self, token: str) -> GitHubService:
        return GitHubService(token, transport=httpx.MockTransport(self.handler))


@pytest.fixture
def e2e(client, auth_headers, remote_repo, tmp_path):
    """Wire a WorkflowManager with scripted LLM / fake GitHub into the API."""

    def build(sandbox, *, script=None, checkpointer=None, sandbox_image=None, max_retries=3, mcp=False,
              mcp_enabled_pref=None):
        bare = remote_repo()
        github = FakeGitHub()
        script = script or llm_script()
        extra = {"sandbox_python_image": sandbox_image} if sandbox_image else {}
        llm, provider = make_llm(script)  # one scripted "model" shared across resumes

        def runtime_factory(workflow_id: str):
            rt = make_runtime(llm, tmp_path, workflow_id=workflow_id, sandbox=sandbox, token="ghp_testtoken",
                              github_factory=github.factory, settings=extra)
            rt.recorder = DBRecorder(workflow_id)
            if mcp:
                from app.mcp_tools.broker import McpToolBroker
                from app.mcp_tools.config import builtin_repo_spec

                rt.mcp = McpToolBroker([builtin_repo_spec(rt.repositories.workspace_dir(workflow_id) / "repo")],
                                       rt.settings, rt.recorder)
            return rt

        settings = get_settings().model_copy(update={"workspace_root": tmp_path / "ws", **extra})
        manager = WorkflowManager(settings, runtime_factory=runtime_factory,
                                  checkpointer=checkpointer or InMemorySaver())
        set_workflow_manager(manager)
        with session_scope() as db:
            user = db.query(User).one()
            repo = GitHubRepository(user_id=user.id, owner="acme", name="calc", full_name="acme/calc",
                                    default_branch="main", html_url="https://github.com/acme/calc",
                                    clone_url=str(bare))
            db.add(repo)
            db.flush()
            repo_id = repo.id
        client.put("/api/settings", json={"workflow_max_retries": max_retries}, headers=auth_headers)
        project = client.post("/api/projects", json={"name": "Calc", "repository_id": repo_id, "base_branch": "main"},
                              headers=auth_headers).json()
        return {"manager": manager, "bare": bare, "github": github, "project": project, "provider": provider}

    yield build
    set_workflow_manager(None)


def _start(client, headers, env, requirement="Add a subtract function to the calculator module"):
    response = client.post("/api/workflows/start", json={"project_id": env["project"]["id"],
                                                          "requirement": requirement}, headers=headers)
    assert response.status_code == 202, response.text
    workflow_id = response.json()["id"]
    env["manager"].wait(workflow_id, timeout=60)
    return workflow_id


def _get(client, headers, workflow_id):
    return client.get(f"/api/workflows/{workflow_id}", headers=headers).json()


def _approve(client, headers, env, workflow_id, approved=True):
    response = client.post(f"/api/workflows/{workflow_id}/approve", json={"approved": approved, "comment": "ok"},
                           headers=headers)
    assert response.status_code == 200, response.text
    env["manager"].wait(workflow_id, timeout=120)
    return _get(client, headers, workflow_id)


def test_full_workflow_with_test_failure_correction_and_pr(client, auth_headers, e2e):
    sandbox = FakeSandbox([1, 0])  # first QA run fails, second passes
    env = e2e(sandbox)
    workflow_id = _start(client, auth_headers, env)

    detail = _get(client, auth_headers, workflow_id)
    assert detail["status"] == "awaiting_approval", detail["error_details"]
    assert detail["pending_approval"]["gate"] == "execution"
    assert detail["pending_approval"]["commands"][0]["test"] == ["python -m pytest -q"]
    assert detail["requirement_analysis"]["title"] == "Add subtract function"
    assert [t["task_key"] for t in detail["tasks"]] == ["T1"]
    assert detail["feature_branch"].startswith("devflow/add-subtract-function-")
    relevant = [f["path"] for f in detail["repository_analysis"]["relevant_files"]]
    assert "does/not/exist.py" not in relevant  # hallucinated reference dropped

    detail = _approve(client, auth_headers, env, workflow_id)
    assert detail["status"] == "awaiting_approval", detail["error_details"]
    assert detail["pending_approval"]["gate"] == "release"
    assert detail["pending_approval"]["test_status"] == "passed"
    assert detail["retry_count"] == 1
    nodes = [a["node"] for a in detail["agent_executions"]]
    assert nodes.count("backend_development") == 2 and nodes.count("testing") == 2
    assert len(sandbox.calls) == 2

    detail = _approve(client, auth_headers, env, workflow_id)
    assert detail["status"] == "completed", detail["error_details"]
    assert detail["pull_request_url"] == "https://github.com/acme/calc/pull/7"

    # Branch pushed to the "remote" with only the approved files, base branch untouched.
    branch = detail["feature_branch"]
    files = git(env["bare"], "show", "--name-only", "--format=", branch).split()
    assert sorted(files) == ["app/calc.py", "tests/test_calc.py"]
    assert "return a - b" in git(env["bare"], "show", f"{branch}:app/calc.py")
    assert "subtract" not in git(env["bare"], "show", "main:app/calc.py")

    pr = env["github"].created[0]
    assert pr["head"] == branch and pr["base"] == "main"
    assert "subtract(5, 3) == 2" in pr["body"] and "## Test results" in pr["body"]
    assert "ghp_testtoken" not in json.dumps(env["provider"].calls)  # token never reached the LLM

    results = client.get(f"/api/workflows/{workflow_id}/results", headers=auth_headers).json()
    assert [t["status"] for t in results["test_results"]] == ["failed", "passed"]
    assert results["review_reports"][0]["approved"] is True
    assert results["pull_request"]["number"] == 7
    assert {f["path"] for f in results["file_changes"] if f["approved"]} == {"app/calc.py", "tests/test_calc.py"}
    assert "+def subtract" in next(f["diff"] for f in results["file_changes"] if f["path"] == "app/calc.py")

    logs = client.get(f"/api/workflows/{workflow_id}/logs", headers=auth_headers).json()
    assert any("Tests failed" in entry["message"] for entry in logs)
    stats = client.get("/api/dashboard/stats", headers=auth_headers).json()
    assert stats["successful_workflows"] == 1 and stats["recent_pull_requests"][0]["number"] == 7
    prs = client.get("/api/github/pull-requests", headers=auth_headers).json()
    assert prs[0]["url"] == "https://github.com/acme/calc/pull/7"


def test_max_retries_reached_fails_workflow(client, auth_headers, e2e):
    env = e2e(FakeSandbox([1, 1, 1, 1]), max_retries=1)
    workflow_id = _start(client, auth_headers, env)
    detail = _approve(client, auth_headers, env, workflow_id)
    assert detail["status"] == "failed"
    assert "Maximum retries" in detail["error_details"]["message"]
    assert "max_retries_exceeded" in [a["node"] for a in detail["agent_executions"]]
    assert env["github"].created == []


def test_review_rejection_routes_feedback_to_developer(client, auth_headers, e2e):
    script = llm_script()
    script["CodeChangeSet*"] = [script["CodeChangeSet*"][0] | {"changes": [
        {"path": "app/calc.py", "action": "modify", "content": FIXED},
        {"path": "tests/test_calc.py", "action": "modify", "content": NEW_TEST}]},
        {"summary": "validate", "changes": [{"path": "app/calc.py", "action": "modify",
                                              "content": FIXED + "\n# validated inputs\n"}]}]
    script["LLMReview*"] = [
        {"approved": False, "summary": "Missing input validation", "issues": [
            {"severity": "high", "category": "validation", "file": "app/calc.py", "message": "validate types"}]},
        {"approved": True, "summary": "Fixed", "issues": []},
    ]
    del script["LLMReview"]
    env = e2e(FakeSandbox([0, 0]), script=script)
    workflow_id = _start(client, auth_headers, env)
    detail = _approve(client, auth_headers, env, workflow_id)
    assert detail["status"] == "awaiting_approval" and detail["pending_approval"]["gate"] == "release"
    results = client.get(f"/api/workflows/{workflow_id}/results", headers=auth_headers).json()
    assert [r["approved"] for r in results["review_reports"]] == [False, True]
    fix_prompt = env["provider"].calls
    assert any("validate types" in json.dumps(c["messages"]) for c in fix_prompt if c["schema"] == "CodeChangeSet")


def test_rejecting_release_cancels_without_push(client, auth_headers, e2e):
    env = e2e(FakeSandbox([0]))
    workflow_id = _start(client, auth_headers, env)
    _approve(client, auth_headers, env, workflow_id)
    detail = _approve(client, auth_headers, env, workflow_id, approved=False)
    assert detail["status"] == "cancelled"
    assert env["github"].created == []
    heads = git(env["bare"], "branch", "--list")
    assert "devflow/" not in heads


def test_cancel_while_awaiting_approval(client, auth_headers, e2e):
    env = e2e(FakeSandbox([0]))
    workflow_id = _start(client, auth_headers, env)
    response = client.post(f"/api/workflows/{workflow_id}/cancel", headers=auth_headers)
    assert response.json()["status"] == "cancelled"
    assert client.post(f"/api/workflows/{workflow_id}/approve", json={"approved": True},
                       headers=auth_headers).status_code == 409
    assert client.post(f"/api/workflows/{workflow_id}/cancel", headers=auth_headers).status_code == 409


def test_cancellation_flag_stops_running_workflow(client, auth_headers, e2e):
    env = e2e(FakeSandbox([0]))
    workflow_id = _start(client, auth_headers, env)
    with session_scope() as db:  # cancellation requested while the next stage runs
        db.get(WorkflowExecution, workflow_id).cancel_requested = True
    detail = _approve(client, auth_headers, env, workflow_id)
    assert detail["status"] == "cancelled"
    assert "testing" not in [a["node"] for a in detail["agent_executions"]]


class SimulatedCrash(BaseException):
    """Simulates the process dying (not an ordinary, handled exception)."""


class CrashOnceSandbox(FakeSandbox):
    def __init__(self):
        super().__init__([0])
        self.crashed = False

    def run(self, *args, **kwargs):
        if not self.crashed:
            self.crashed = True
            raise SimulatedCrash()
        return super().run(*args, **kwargs)


def test_checkpoint_recovery_after_crash(client, auth_headers, e2e, tmp_path):
    conn = sqlite3.connect(tmp_path / "checkpoints.sqlite", check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    sandbox = CrashOnceSandbox()
    env = e2e(sandbox, checkpointer=saver)
    workflow_id = _start(client, auth_headers, env)
    client.post(f"/api/workflows/{workflow_id}/approve", json={"approved": True}, headers=auth_headers)
    with pytest.raises(SimulatedCrash):
        env["manager"].wait(workflow_id, timeout=60)
    assert _get(client, auth_headers, workflow_id)["status"] == "running"  # process "died" mid-testing

    # A new manager (fresh process) with the same checkpoint store resumes the workflow.
    restarted = WorkflowManager(env["manager"].settings, runtime_factory=env["manager"].runtime_factory,
                                checkpointer=SqliteSaver(sqlite3.connect(tmp_path / "checkpoints.sqlite",
                                                                         check_same_thread=False)))
    set_workflow_manager(restarted)
    assert restarted.resume_interrupted() == [workflow_id]
    restarted.wait(workflow_id, timeout=60)
    detail = _get(client, auth_headers, workflow_id)
    assert detail["status"] == "awaiting_approval" and detail["pending_approval"]["gate"] == "release"
    nodes = [a["node"] for a in detail["agent_executions"]]
    assert nodes.count("requirement_analysis") == 1  # earlier stages were not re-run


@pytest.fixture(scope="session")
def pytest_image(tmp_path_factory):
    """A python sandbox image with pytest preinstalled (tests run with network disabled)."""
    if not docker_available():
        pytest.skip("Docker daemon not available")
    image = "devflow-test/python-pytest:3.11"
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0:
        return image
    wheels = tmp_path_factory.mktemp("wheels")
    subprocess.run(["pip", "download", "pytest", "-q", "-d", str(wheels), "--only-binary=:all:",
                    "--python-version", "3.11"], check=True)
    base = get_settings().sandbox_python_image
    subprocess.run(["docker", "pull", base], check=True, capture_output=True)
    cid = subprocess.run(["docker", "create", base, "sh", "-c", "pip install -q --no-index /wheels/*.whl"],
                         check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["docker", "cp", f"{wheels}/.", f"{cid}:/wheels"], check=True)
    subprocess.run(["docker", "start", "-a", cid], check=True)
    subprocess.run(["docker", "commit", cid, image], check=True, capture_output=True)
    subprocess.run(["docker", "rm", cid], capture_output=True)
    return image


@pytest.mark.docker
def test_full_workflow_with_real_docker_sandbox(client, auth_headers, e2e, pytest_image):
    from app.services.execution_service import DockerSandbox

    settings = get_settings().model_copy(update={"sandbox_python_image": pytest_image,
                                                 "sandbox_command_timeout_seconds": 120})
    env = e2e(DockerSandbox(settings, allow_network_for_install=False), sandbox_image=pytest_image)
    workflow_id = _start(client, auth_headers, env)
    detail = _approve(client, auth_headers, env, workflow_id)
    assert detail["status"] == "awaiting_approval", detail["error_details"]
    results = client.get(f"/api/workflows/{workflow_id}/results", headers=auth_headers).json()
    first, second = results["test_results"]
    assert first["status"] == "failed"  # the buggy implementation really failed pytest in the container
    assert "assert" in json.dumps(first["commands"]).lower()
    assert second["status"] == "passed"
    detail = _approve(client, auth_headers, env, workflow_id)
    assert detail["status"] == "completed"
    assert Path(env["manager"].settings.workspace_root, workflow_id).exists() is False  # workspace cleaned up


def _traced_script():
    script = llm_script()
    # MCP: the architect reads a file through the repo MCP server, then finishes; later agents just finish.
    script["ToolDecision*"] = [
        {"action": "call_tool", "server": "devflow-repo", "tool": "read_file", "arguments": {"path": "app/calc.py"}},
        {"action": "finish"},
    ]
    return script


def test_workflow_with_mcp_tools_and_langsmith_tracing(client, auth_headers, e2e):
    from app.observability.tracing import Tracing, set_tracing
    from tests.conftest import FakeLangSmith

    fake = FakeLangSmith()
    settings = get_settings().model_copy(update={"langsmith_tracing": True, "langsmith_api_key": "lsv2_test"})
    set_tracing(Tracing(settings, client_options=fake.client_options()))
    try:
        env = e2e(FakeSandbox([0]), script=_traced_script(), mcp=True)
        workflow_id = _start(client, auth_headers, env)
        first = _get(client, auth_headers, workflow_id)
        assert first["status"] == "awaiting_approval", first["error_details"]
        detail = _approve(client, auth_headers, env, workflow_id)          # execution gate -> release gate
        assert detail["pending_approval"]["gate"] == "release"
        detail = _approve(client, auth_headers, env, workflow_id)          # release gate -> completed
        assert detail["status"] == "completed", detail["error_details"]

        # --- MCP: tool call executed for real over stdio, audited and visible in the results
        results = client.get(f"/api/workflows/{workflow_id}/results", headers=auth_headers).json()
        calls = results["tool_calls"]
        assert [(c["agent"], c["server"], c["tool"], c["status"]) for c in calls] == [
            ("architect", "devflow-repo", "read_file", "ok")]
        assert "return a + b" in calls[0]["result_preview"] and calls[0]["arguments"] == {"path": "app/calc.py"}
        architect_prompts = [c for c in env["provider"].calls if c["schema"] == "ArchitecturePlan"]
        assert "UNTRUSTED" in architect_prompts[0]["messages"][1]["content"]  # findings reached the model, fenced
        assert "return a + b" in architect_prompts[0]["messages"][1]["content"]

        # --- LangSmith: three graph segments (start, execution approval, release approval), all linked
        assert len(detail["trace_run_ids"]) == 3
        roots = [fake.runs[r] for r in detail["trace_run_ids"]]
        assert [r["name"] for r in roots] == ["devflow-workflow", "devflow-workflow-resume", "devflow-workflow-resume"]
        assert all(r["extra"]["metadata"]["thread_id"] == workflow_id for r in roots)
        assert roots[0]["extra"]["metadata"]["repository"] == "acme/calc"
        node_names = {r["name"] for r in fake.runs.values() if r.get("run_type") == "chain"}
        assert {"requirement_analysis", "architecture_design", "testing", "code_review", "github_release"} <= node_names
        llm_runs = [r for r in fake.runs.values() if str(r.get("name", "")).startswith("llm:")]
        assert {"llm:requirement_analyst", "llm:architect", "llm:backend_developer", "llm:code_reviewer"} <= {
            r["name"] for r in llm_runs}
        architect_llm = fake.runs_named("llm:architect")[0]
        assert "architecture_design" in fake.ancestors(architect_llm)
        tool_runs = fake.runs_named("mcp:devflow-repo.read_file")
        assert len(tool_runs) == 1 and tool_runs[0]["run_type"] == "tool"
        assert "architecture_design" in fake.ancestors(tool_runs[0])  # the MCP call nests under the architect node
        feedback = {f["key"]: f for f in fake.feedback()}
        assert feedback["human_approval_execution"]["score"] == 1.0 and feedback["human_approval_release"]["score"] == 1.0
        assert feedback["workflow_completed"]["score"] == 1.0 and feedback["tests_passed"]["score"] == 1.0
        assert feedback["review_approved"]["score"] == 1.0
        sent = fake.everything_sent()
        assert "ghp_testtoken" not in sent and "Authorization" not in sent  # no credentials in any trace

        trace = client.get(f"/api/workflows/{workflow_id}/trace", headers=auth_headers).json()
        assert trace["enabled"] and trace["run_ids"] == detail["trace_run_ids"] and trace["project"] == "devflow-ai"
    finally:
        set_tracing(None)


def test_tracing_disabled_records_nothing(client, auth_headers, e2e):
    env = e2e(FakeSandbox([0]))
    workflow_id = _start(client, auth_headers, env)
    detail = _get(client, auth_headers, workflow_id)
    assert detail["trace_run_ids"] == []
    trace = client.get(f"/api/workflows/{workflow_id}/trace", headers=auth_headers).json()
    assert trace["enabled"] is False and "disabled" in trace["note"]
    assert client.get(f"/api/workflows/{workflow_id}/results", headers=auth_headers).json()["tool_calls"] == []


def test_devflow_mcp_server_drives_a_workflow_but_cannot_approve(client, auth_headers, e2e):
    """An MCP client (e.g. Claude Code) can start and monitor workflows; approvals stay human-only."""
    import asyncio

    from mcp import Client

    from app.mcp_tools.devflow_server import create_server

    env = e2e(FakeSandbox([0]))
    api = client  # the FastAPI TestClient is an httpx client, so the MCP server can wrap it directly
    api.headers.update(auth_headers)
    server = create_server(api)

    async def scenario():
        async with Client(server) as mcp_client:
            names = {t.name for t in (await mcp_client.list_tools()).tools}
            assert not any("approve" in n for n in names)  # by design
            assert {"start_workflow", "get_workflow", "cancel_workflow", "list_projects"} <= names
            projects = (await mcp_client.call_tool("list_projects", {})).structured_content
            project_id = (projects.get("result") or projects)[0]["id"]
            started = (await mcp_client.call_tool("start_workflow", {
                "project_id": project_id, "requirement": "Add a subtract function to the calculator module"})
            ).structured_content
            workflow_id = started["workflow_id"]
            await asyncio.to_thread(env["manager"].wait, workflow_id, 60)
            status = (await mcp_client.call_tool("get_workflow", {"workflow_id": workflow_id})).structured_content
            assert status["status"] == "awaiting_approval"
            assert status["awaiting_human_approval"] == {
                "gate": "execution", "title": status["awaiting_human_approval"]["title"], "where": "DevFlow dashboard"}
            assert {a["agent"] for a in status["agents"]} >= {"requirement_analyst", "architect"}
            missing = await mcp_client.call_tool("get_workflow", {"workflow_id": "nope"})
            assert missing.is_error and "404" in missing.content[0].text and "Workflow not found" in missing.content[0].text
            cancelled = (await mcp_client.call_tool("cancel_workflow", {"workflow_id": workflow_id})).structured_content
            assert cancelled["status"] == "cancelled"
            logs = (await mcp_client.call_tool("get_workflow_logs", {"workflow_id": workflow_id})).structured_content
            assert any("Waiting for human approval" in e["message"] for e in (logs.get("result") or logs))

    asyncio.run(scenario())
