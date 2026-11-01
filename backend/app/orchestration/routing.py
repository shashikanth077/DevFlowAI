"""Conditional edge functions.

Routing is a pure function of the state so that a resumed workflow takes the
same path it would have taken without interruption.
"""

from __future__ import annotations

from langgraph.graph import END

from app.orchestration.state import ProjectState

DEV_NODES = {"frontend": "frontend_development", "backend": "backend_development"}


def _stopped(state: ProjectState) -> bool:
    return state.get("workflow_status") in ("failed", "cancelled")


def development_order(state: ProjectState) -> tuple[str, list[str]]:
    """Return ("parallel" | "sequential", roles) for the current development round.

    Initial implementation runs the two developers in parallel unless a task of
    one agent depends on a task of the other; then the dependency runs first.
    Correction rounds always run in parallel (feedback is independent per agent).
    """
    roles = [r for r in ("backend", "frontend") if r in (state.get("active_agents") or [])]
    if len(roles) < 2 or state.get("fix_feedback"):
        return "parallel", roles
    tasks = {t["id"]: t for t in state.get("development_tasks", [])}
    depends_on: dict[str, set[str]] = {"frontend": set(), "backend": set()}
    for task in tasks.values():
        for dep in task.get("dependencies", []):
            if dep in tasks and tasks[dep]["assigned_agent"] != task["assigned_agent"]:
                depends_on[task["assigned_agent"]].add(tasks[dep]["assigned_agent"])
    if depends_on["frontend"] and not depends_on["backend"]:
        return "sequential", ["backend", "frontend"]
    if depends_on["backend"] and not depends_on["frontend"]:
        return "sequential", ["frontend", "backend"]
    return "parallel", roles


def continue_or_end(next_node: str):
    def route(state: ProjectState) -> str:
        return END if _stopped(state) else next_node

    route.__name__ = f"route_to_{next_node}"
    return route


def route_to_development(state: ProjectState) -> list[str] | str:
    """After task planning or a failed test/review round: start development agents."""
    if _stopped(state):
        return END
    mode, roles = development_order(state)
    if not roles:
        return END
    if mode == "sequential":
        return DEV_NODES[roles[0]]
    return [DEV_NODES[r] for r in roles]


def after_development(role: str):
    def route(state: ProjectState) -> str:
        if _stopped(state):
            return END
        mode, roles = development_order(state)
        if mode == "sequential" and roles[0] == role:
            return DEV_NODES[roles[1]]
        return "development_join"

    route.__name__ = f"after_{role}_development"
    return route


def route_after_tests(state: ProjectState) -> list[str] | str:
    status = state.get("workflow_status")
    if status == "cancelled":
        return END                      # workflow cancellation
    if status == "failed":
        return END                      # unrecoverable error (e.g. sandbox unavailable)
    if status == "tests_failed":
        if state.get("retry_count", 0) > state.get("max_retries", 0):
            return "max_retries_exceeded"   # maximum retry reached
        return route_to_development(state)  # failed tests -> responsible developer(s)
    return "code_review"                # successful tests (or explicitly reported as not run)


def route_after_review(state: ProjectState) -> list[str] | str:
    status = state.get("workflow_status")
    if status in ("cancelled", "failed"):
        return END
    if status == "review_failed":
        if state.get("retry_count", 0) > state.get("max_retries", 0):
            return "max_retries_exceeded"
        return route_to_development(state)  # failed review -> responsible developer(s)
    return "release_approval"           # successful review
