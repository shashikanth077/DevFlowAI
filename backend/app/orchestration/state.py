"""Shared LangGraph workflow state.

Everything in the state is JSON-serialisable so it can be checkpointed.
Secrets (GitHub token, API keys) are deliberately *not* part of the state;
nodes obtain them from the runtime at execution time.

Keys written by the frontend and backend development nodes - which run in
parallel in the same super-step - use reducers so concurrent updates merge
instead of conflicting.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

WorkflowStatusValue = Literal[
    "running", "awaiting_approval", "tests_failed", "review_failed", "completed", "failed", "cancelled"
]


def merge_tasks(current: list[dict] | None, update: list[dict] | None) -> list[dict]:
    """Merge task lists by ``id`` (later updates win, order preserved)."""
    if update is None:
        return current or []
    if current is None:
        return list(update)
    if update and update[0].get("__replace__"):
        return [t for t in update if not t.get("__replace__")]
    merged = {t["id"]: t for t in current}
    order = [t["id"] for t in current]
    for task in update:
        if task["id"] not in merged:
            order.append(task["id"])
        merged[task["id"]] = {**merged.get(task["id"], {}), **task}
    return [merged[i] for i in order]


def merge_unique(current: list[str] | None, update: list[str] | None) -> list[str]:
    result = list(current or [])
    for item in update or []:
        if item not in result:
            result.append(item)
    return result


_TERMINAL = ("failed", "cancelled", "completed")


def merge_status(current: str | None, update: str | None) -> str | None:
    """Terminal statuses are sticky so a parallel branch cannot 'un-fail' a workflow."""
    if update is None:
        return current
    if current in _TERMINAL and update not in _TERMINAL:
        return current
    if current == "cancelled":
        return current
    return update


def keep_last(current: Any, update: Any) -> Any:
    return current if update is None else update


def merge_dict(current: dict | None, update: dict | None) -> dict:
    return {**(current or {}), **(update or {})}


class ProjectState(TypedDict, total=False):
    # Identity / inputs
    project_id: str
    workflow_id: str
    user_id: str
    repository_full_name: str
    repository_url: str
    repository_path: str
    base_branch: str
    feature_branch: str
    user_requirement: str

    # Agent outputs
    requirement_analysis: dict[str, Any]
    acceptance_criteria: list[str]
    repository_analysis: dict[str, Any]
    architecture_plan: dict[str, Any]
    development_tasks: Annotated[list[dict[str, Any]], merge_tasks]
    generated_files: Annotated[list[str], merge_unique]
    modified_files: Annotated[list[str], merge_unique]
    file_ownership: Annotated[dict[str, str], merge_dict]  # path -> agent role that changed it
    agent_summaries: Annotated[dict[str, str], merge_dict]
    test_results: dict[str, Any]
    review_feedback: dict[str, Any]

    # Control flow
    active_agents: list[str]          # development agents that must run in the current round
    fix_feedback: dict[str, list[str]]  # role -> actionable feedback for the next correction round
    workflow_status: Annotated[WorkflowStatusValue, merge_status]
    retry_count: int
    max_retries: int
    execution_approved: bool
    release_approved: bool
    approval_comment: str
    approved_diff_hash: str

    # Results
    commit_id: str
    pull_request_url: str
    pull_request_number: int
    error_details: Annotated[dict[str, Any], keep_last]
