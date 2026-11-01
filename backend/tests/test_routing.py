from langgraph.graph import END

from app.orchestration.routing import (
    after_development,
    development_order,
    route_after_review,
    route_after_tests,
    route_to_development,
)
from app.orchestration.state import merge_status, merge_tasks

TASKS = [
    {"id": "T1", "assigned_agent": "backend", "dependencies": []},
    {"id": "T2", "assigned_agent": "frontend", "dependencies": ["T1"]},
]


def test_parallel_when_independent():
    state = {"active_agents": ["frontend", "backend"], "development_tasks": [
        {"id": "T1", "assigned_agent": "backend", "dependencies": []},
        {"id": "T2", "assigned_agent": "frontend", "dependencies": []}]}
    assert development_order(state) == ("parallel", ["backend", "frontend"])
    assert route_to_development(state) == ["backend_development", "frontend_development"]
    assert after_development("frontend")(state) == "development_join"


def test_sequential_when_cross_dependency():
    state = {"active_agents": ["frontend", "backend"], "development_tasks": TASKS}
    assert development_order(state) == ("sequential", ["backend", "frontend"])
    assert route_to_development(state) == "backend_development"
    assert after_development("backend")(state) == "frontend_development"
    assert after_development("frontend")(state) == "development_join"


def test_fix_rounds_only_run_responsible_agents():
    state = {"active_agents": ["frontend"], "development_tasks": TASKS, "fix_feedback": {"frontend": ["x"]},
             "workflow_status": "tests_failed", "retry_count": 1, "max_retries": 3}
    assert route_after_tests(state) == ["frontend_development"]


def test_test_routing():
    assert route_after_tests({"workflow_status": "running"}) == "code_review"
    assert route_after_tests({"workflow_status": "cancelled"}) == END
    assert route_after_tests({"workflow_status": "failed"}) == END
    assert route_after_tests({"workflow_status": "tests_failed", "retry_count": 4, "max_retries": 3,
                              "active_agents": ["backend"]}) == "max_retries_exceeded"


def test_review_routing():
    assert route_after_review({"workflow_status": "running"}) == "release_approval"
    assert route_after_review({"workflow_status": "review_failed", "retry_count": 1, "max_retries": 2,
                               "active_agents": ["backend"]}) == ["backend_development"]
    assert route_after_review({"workflow_status": "review_failed", "retry_count": 3, "max_retries": 2,
                               "active_agents": ["backend"]}) == "max_retries_exceeded"


def test_reducers():
    assert merge_status("failed", "running") == "failed"
    assert merge_status("tests_failed", "running") == "running"
    assert merge_status("running", "cancelled") == "cancelled"
    merged = merge_tasks([{"id": "a", "status": "pending"}, {"id": "b", "status": "pending"}],
                         [{"id": "b", "status": "completed"}])
    assert [t["status"] for t in merged] == ["pending", "completed"]
    assert merge_tasks([{"id": "a"}], [{"id": "_", "__replace__": True}, {"id": "z"}]) == [{"id": "z"}]
