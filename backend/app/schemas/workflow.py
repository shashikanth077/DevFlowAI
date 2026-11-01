from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import APIModel
from app.schemas.integrations import ToolCallOut
from app.schemas.project import validate_branch_name
from app.schemas.task import TaskOut

WorkflowStatus = Literal[
    "queued", "running", "awaiting_approval", "completed", "failed", "cancelled"
]


class WorkflowStartRequest(BaseModel):
    project_id: str
    requirement: str = Field(min_length=10, max_length=20_000)
    base_branch: str | None = Field(default=None, max_length=200)

    @field_validator("base_branch")
    @classmethod
    def _branch(cls, value: str | None) -> str | None:
        return validate_branch_name(value) if value else value


class ApprovalRequest(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=2000)


class AgentExecutionOut(APIModel):
    id: str
    agent_name: str
    node: str
    attempt: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    output: dict | None
    error: str | None


class WorkflowLogOut(APIModel):
    id: int
    created_at: datetime
    level: str
    agent: str | None
    message: str
    data: dict | None


class WorkflowSummary(APIModel):
    id: str
    project_id: str
    project_name: str = ""
    repository_full_name: str = ""
    requirement: str
    base_branch: str
    feature_branch: str | None
    status: str
    current_stage: str | None
    retry_count: int
    pull_request_url: str | None
    created_at: datetime
    completed_at: datetime | None


class WorkflowDetail(WorkflowSummary):
    max_retries: int
    cancel_requested: bool
    pending_approval: dict | None
    approvals: list[dict[str, Any]]
    requirement_analysis: dict | None
    repository_analysis: dict | None
    architecture_plan: dict | None
    error_details: dict | None
    commit_id: str | None
    trace_run_ids: list[str] = []
    started_at: datetime | None
    agent_executions: list[AgentExecutionOut]
    tasks: list[TaskOut]


class FileChangeOut(APIModel):
    id: str
    path: str
    change_type: str
    agent: str
    diff: str
    additions: int
    deletions: int
    approved: bool


class TestResultOut(APIModel):
    __test__ = False

    id: str
    attempt: int
    status: str
    summary: str
    commands: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    coverage_notes: list[str]
    duration_ms: int
    created_at: datetime


class ReviewReportOut(APIModel):
    id: str
    attempt: int
    approved: bool
    summary: str
    issues: list[dict[str, Any]]
    automated_findings: list[dict[str, Any]]
    diff_hash: str
    reviewer_model: str
    created_at: datetime


class PullRequestOut(APIModel):
    id: str
    workflow_id: str
    repository_full_name: str
    number: int
    url: str
    title: str
    head_branch: str
    base_branch: str
    commit_sha: str
    state: str
    draft: bool
    merged: bool
    created_at: datetime


class WorkflowResults(BaseModel):
    workflow_id: str
    status: str
    feature_branch: str | None
    commit_id: str | None
    pull_request_url: str | None
    file_changes: list[FileChangeOut]
    test_results: list[TestResultOut]
    review_reports: list[ReviewReportOut]
    tool_calls: list[ToolCallOut] = []
    pull_request: PullRequestOut | None


class DashboardStats(BaseModel):
    total_projects: int
    active_workflows: int
    successful_workflows: int
    failed_workflows: int
    awaiting_approval: int
    recent_pull_requests: list[PullRequestOut]
    recent_workflows: list[WorkflowSummary]
