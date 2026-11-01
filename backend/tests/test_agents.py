import pytest

from app.agents.backend_agent import BackendDevelopmentAgent
from app.agents.review_agent import CodeReviewAgent, feedback_from_review
from app.agents.task_agent import TaskOrchestratorAgent
from app.agents.testing_agent import TestingAgent
from app.core.errors import DevFlowError
from app.schemas.repository import ProjectComponent
from app.services.execution_service import CommandResult, SandboxRun
from tests.conftest import SAMPLE_CALC, make_llm, make_runtime

COMPONENTS = [
    ProjectComponent(path="frontend", kind="frontend", sandbox_image="node", test_commands=["npm test"]).model_dump(),
    ProjectComponent(path="backend", kind="backend", sandbox_image="py", test_commands=["pytest"],
                     install_commands=["pip install -r requirements.txt"]).model_dump(),
]


def _state(**extra):
    base = {
        "requirement_analysis": {"summary": "s", "title": "t"},
        "acceptance_criteria": ["works"],
        "architecture_plan": {"approach": "a", "file_plan": []},
        "repository_analysis": {"components": COMPONENTS, "file_tree": "", "relevant_files": []},
    }
    return {**base, **extra}


def test_task_planning_validates_ids_dependencies_and_cycles(tmp_path):
    plan = {"tasks": [
        {"id": "T1", "title": "API", "assigned_agent": "backend", "dependencies": ["T2"],
         "target_files": ["backend/app/api.py"]},
        {"id": "T2", "title": "UI", "assigned_agent": "BACKEND", "dependencies": ["T1", "T9"],
         "target_files": ["frontend/src/List.tsx"]},
        {"id": "T1", "title": "dup", "assigned_agent": "frontend", "dependencies": []},
    ]}
    llm, _ = make_llm({"TaskPlan": plan})
    tasks = TaskOrchestratorAgent(make_runtime(llm, tmp_path)).run(_state())
    by_id = {t.id: t for t in tasks}
    assert len(tasks) == 3 and len(by_id) == 3                       # duplicate id renamed
    assert by_id["T2"].assigned_agent == "frontend"                  # reassigned by file location
    assert "T9" not in by_id["T2"].dependencies                      # unknown dependency dropped
    # the T1 <-> T2 cycle was broken and every task has a position
    assert sorted(t.position for t in tasks) == [0, 1, 2]
    order = [t.id for t in tasks]
    for task in tasks:
        for dep in task.dependencies:
            assert order.index(dep) < order.index(task.id)


def test_task_planning_falls_back_to_file_plan(tmp_path):
    llm, _ = make_llm({"TaskPlan": {"tasks": []}})
    state = _state(architecture_plan={"approach": "a", "file_plan": [
        {"path": "backend/app/x.py", "action": "create", "area": "backend"},
        {"path": "frontend/src/X.tsx", "action": "create", "area": "frontend"},
    ]})
    tasks = TaskOrchestratorAgent(make_runtime(llm, tmp_path)).run(state)
    assert [t.assigned_agent for t in tasks] == ["backend", "frontend"]
    assert tasks[1].dependencies == ["T1"]


def _dev_setup(tmp_path, remote_repo, changes):
    llm, provider = make_llm({"CodeChangeSet": {"summary": "did it", "changes": changes}})
    rt = make_runtime(llm, tmp_path)
    rt.repositories.clone(str(remote_repo()), "main", rt.workflow_id, token=None)
    task = {"id": "T1", "title": "t", "description": "", "assigned_agent": "backend", "dependencies": [],
            "target_files": ["app/calc.py"], "acceptance_criteria": [], "status": "pending", "attempts": 0,
            "position": 0}
    state = _state(development_tasks=[task], file_ownership={},
                   repository_analysis={"components": [], "file_tree": "", "relevant_files": []})
    return rt, state, provider


def test_development_agent_applies_valid_changes(tmp_path, remote_repo):
    new_calc = SAMPLE_CALC + "\n\ndef sub(a: int, b: int) -> int:\n    return a - b\n"
    rt, state, provider = _dev_setup(tmp_path, remote_repo, [
        {"path": "app/calc.py", "action": "modify", "content": new_calc},
        {"path": "tests/test_sub.py", "action": "create", "content": "from app.calc import sub\n"},
    ])
    update = BackendDevelopmentAgent(rt).run(state)
    assert update["modified_files"] == ["app/calc.py"]
    assert update["generated_files"] == ["tests/test_sub.py"]
    assert update["development_tasks"][0]["status"] == "completed"
    assert "def sub" in rt.workspace().read_file("app/calc.py")
    # the model saw the current file content before modifying it
    assert "def add(a: int, b: int)" in provider.calls[0]["messages"][1]["content"]


@pytest.mark.parametrize("change, reason", [
    ({"path": "../escape.py", "action": "create", "content": "x"}, "traversal"),
    ({"path": ".env", "action": "create", "content": "SECRET=x"}, "Access to credential-like file"),
    ({"path": "app/calc.py", "action": "modify", "content": "def add():\n    ...rest of the code\n"}, "placeholder"),
    ({"path": "README.md", "action": "modify", "content": "# overwritten\n"}, "not reviewed"),
])
def test_development_agent_rejects_unsafe_changes(tmp_path, remote_repo, change, reason):
    rt, state, _ = _dev_setup(tmp_path, remote_repo, [change])
    with pytest.raises(DevFlowError):
        BackendDevelopmentAgent(rt).run(state)
    assert any(reason in message for _, message, _ in rt.recorder.logs)
    assert rt.workspace().read_file("README.md") == "# Sample service\n"


def test_development_agent_rejects_truncating_rewrites(tmp_path, remote_repo):
    rt, state, _ = _dev_setup(tmp_path, remote_repo, [{"path": "app/big.py", "action": "modify", "content": "x = 1\n"}])
    ws = rt.workspace()
    (ws.root / "app/big.py").write_text("\n".join(f"line_{i} = {i}" for i in range(100)) + "\n")
    state["development_tasks"][0]["target_files"] = ["app/big.py"]
    with pytest.raises(DevFlowError):
        BackendDevelopmentAgent(rt).run(state)
    assert any("shrinks file" in m for _, m, _ in rt.recorder.logs)


def test_development_agent_respects_other_agents_files(tmp_path, remote_repo):
    rt, state, _ = _dev_setup(tmp_path, remote_repo, [
        {"path": "app/calc.py", "action": "modify", "content": SAMPLE_CALC + "\n# change\n"}])
    state["file_ownership"] = {"app/calc.py": "frontend"}
    with pytest.raises(DevFlowError):
        BackendDevelopmentAgent(rt).run(state)
    assert any("owned by the frontend agent" in m for _, m, _ in rt.recorder.logs)


class FakeSandbox:
    allow_network_for_install = False

    def __init__(self, exit_codes):
        self.exit_codes = list(exit_codes)
        self.calls = []

    def run(self, workspace, *, image, workdir, setup_commands, commands):
        self.calls.append({"image": image, "workdir": workdir, "setup": setup_commands, "commands": commands})
        code = self.exit_codes.pop(0) if self.exit_codes else 0
        return SandboxRun(setup=[CommandResult(" && ".join(setup_commands), 0, "", "", 5)],
                          commands=[CommandResult(c, code, "1 failed" if code else "ok", "", 10) for c in commands])


def test_testing_agent_runs_only_changed_components(tmp_path, remote_repo):
    llm, _ = make_llm({"FailureAnalysis": {"failures": []}})
    sandbox = FakeSandbox([0])
    rt = make_runtime(llm, tmp_path, sandbox=sandbox)
    rt.repositories.clone(str(remote_repo()), "main", rt.workflow_id, token=None)
    report = TestingAgent(rt).run(_state(generated_files=["backend/app/x.py", "backend/tests/test_x.py"],
                                         modified_files=[]))
    assert report.status == "passed"
    assert sandbox.calls == [{"image": "py", "workdir": "backend", "setup": ["pip install -r requirements.txt"],
                              "commands": ["pytest"]}]


def test_testing_agent_never_reports_success_without_tests(tmp_path, remote_repo):
    llm, _ = make_llm({})
    rt = make_runtime(llm, tmp_path, sandbox=FakeSandbox([]))
    rt.repositories.clone(str(remote_repo()), "main", rt.workflow_id, token=None)
    components = [ProjectComponent(path=".", kind="backend", sandbox_image="py").model_dump()]
    state = _state(generated_files=["app/x.py"], modified_files=[],
                   repository_analysis={"components": components})
    report = TestingAgent(rt).run(state)
    assert report.status == "not_run"
    assert any("no test files" in n.lower() or "no automated test" in n.lower() for n in report.coverage_notes)


def test_testing_agent_assigns_failures(tmp_path, remote_repo):
    llm, _ = make_llm({"FailureAnalysis": {"failures": [
        {"command": "pytest", "summary": "assertion failed", "files": ["backend/app/x.py"]}]}})
    rt = make_runtime(llm, tmp_path, sandbox=FakeSandbox([1]))
    rt.repositories.clone(str(remote_repo()), "main", rt.workflow_id, token=None)
    report = TestingAgent(rt).run(_state(generated_files=["backend/app/x.py"], modified_files=[],
                                         file_ownership={"backend/app/x.py": "backend"}))
    assert report.status == "failed"
    assert report.responsible_agents == ["backend"]


def test_review_blocks_secrets_even_if_llm_approves(tmp_path, remote_repo):
    llm, _ = make_llm({"LLMReview": {"approved": True, "summary": "LGTM", "issues": []}})
    rt = make_runtime(llm, tmp_path)
    ws = rt.repositories.clone(str(remote_repo()), "main", rt.workflow_id, token=None)
    ws.write_file("app/config.py", 'API_TOKEN = "ghp_' + "z" * 36 + '"\n')
    report = CodeReviewAgent(rt).run(_state(file_ownership={"app/config.py": "backend"},
                                            test_results={"status": "passed"}))
    assert not report.approved
    assert any(f.category == "secret" and f.severity == "critical" for f in report.automated_findings)
    assert report.responsible_agents == ["backend"]
    feedback = feedback_from_review(report)
    assert "secret" in " ".join(feedback["backend"]).lower()


def test_review_approves_clean_change(tmp_path, remote_repo):
    llm, _ = make_llm({"LLMReview": {"approved": True, "summary": "Looks good", "issues": [
        {"severity": "Low", "message": "naming nit", "file": "app/calc.py"}]}})
    rt = make_runtime(llm, tmp_path)
    ws = rt.repositories.clone(str(remote_repo()), "main", rt.workflow_id, token=None)
    ws.write_file("app/calc.py", SAMPLE_CALC + "\n\ndef sub(a, b):\n    return a - b\n")
    report = CodeReviewAgent(rt).run(_state(file_ownership={"app/calc.py": "backend"},
                                            test_results={"status": "passed"}))
    assert report.approved and len(report.diff_hash) == 64


def test_developer_prompt_includes_fenced_tool_findings_and_audit_trail(tmp_path, remote_repo):
    from app.mcp_tools.broker import McpToolBroker
    from app.mcp_tools.config import builtin_repo_spec

    new_calc = SAMPLE_CALC + "\n\ndef sub(a: int, b: int) -> int:\n    return a - b\n"
    llm, provider = make_llm({
        "CodeChangeSet": {"summary": "did it", "changes": [{"path": "app/calc.py", "action": "modify", "content": new_calc}]},
        "ToolDecision*": [{"action": "call_tool", "server": "devflow-repo", "tool": "search_code",
                           "arguments": {"query": "def add"}}, {"action": "finish"}],
    })
    rt = make_runtime(llm, tmp_path)
    rt.repositories.clone(str(remote_repo()), "main", rt.workflow_id, token=None)
    rt.mcp = McpToolBroker([builtin_repo_spec(rt.repositories.workspace_dir(rt.workflow_id) / "repo")],
                           rt.settings, rt.recorder)
    task = {"id": "T1", "title": "t", "description": "", "assigned_agent": "backend", "dependencies": [],
            "target_files": ["app/calc.py"], "acceptance_criteria": [], "status": "pending", "attempts": 0,
            "position": 0}
    state = _state(development_tasks=[task], file_ownership={},
                   repository_analysis={"components": [], "file_tree": "", "relevant_files": []})
    try:
        update = BackendDevelopmentAgent(rt).run(state)
    finally:
        rt.close()
    assert update["modified_files"] == ["app/calc.py"]
    prompt = next(c for c in provider.calls if c["schema"] == "CodeChangeSet")["messages"][1]["content"]
    assert "UNTRUSTED" in prompt and "app/calc.py:4: def add(a: int, b: int) -> int:" in prompt
    assert [(c["agent"], c["tool"], c["status"]) for c in rt.recorder.tool_calls] == [
        ("backend_developer", "search_code", "ok")]


def test_agents_work_unchanged_when_mcp_is_off(tmp_path, remote_repo):
    rt, state, provider = _dev_setup(tmp_path, remote_repo, [
        {"path": "app/calc.py", "action": "modify", "content": SAMPLE_CALC + "\n# ok\n"}])
    assert rt.mcp is None
    BackendDevelopmentAgent(rt).run(state)
    assert provider.count("ToolDecision") == 0 and rt.recorder.tool_calls == []
