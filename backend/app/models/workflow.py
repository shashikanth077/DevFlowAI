from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base, TimestampMixin, utcnow
from app.models.base import JSONType, new_id

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import DevelopmentTask


class WorkflowExecution(TimestampMixin, Base):
    __tablename__ = "workflow_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    base_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    feature_branch: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40), index=True, default="queued", nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(60))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending_approval: Mapped[dict | None] = mapped_column(JSONType)
    approvals: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    requirement_analysis: Mapped[dict | None] = mapped_column(JSONType)
    repository_analysis: Mapped[dict | None] = mapped_column(JSONType)
    architecture_plan: Mapped[dict | None] = mapped_column(JSONType)
    error_details: Mapped[dict | None] = mapped_column(JSONType)
    commit_id: Mapped[str | None] = mapped_column(String(64))
    pull_request_url: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="workflows")
    agent_executions: Mapped[list[AgentExecution]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="AgentExecution.started_at"
    )
    tasks: Mapped[list[DevelopmentTask]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="DevelopmentTask.position"
    )
    file_changes: Mapped[list[FileChange]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    test_results: Mapped[list[TestExecutionResult]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="TestExecutionResult.created_at"
    )
    review_reports: Mapped[list[CodeReviewReport]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="CodeReviewReport.created_at"
    )
    pull_request: Mapped[PullRequest | None] = relationship(
        back_populates="workflow", uselist=False, cascade="all, delete-orphan"
    )


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(60), nullable=False)
    node: Mapped[str] = mapped_column(String(60), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    output: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)

    workflow: Mapped[WorkflowExecution] = relationship(back_populates="agent_executions")


class WorkflowLog(Base):
    __tablename__ = "workflow_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    level: Mapped[str] = mapped_column(String(10), default="info", nullable=False)
    agent: Mapped[str | None] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONType)


class FileChange(TimestampMixin, Base):
    __tablename__ = "file_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)  # created | modified | deleted
    agent: Mapped[str] = mapped_column(String(60), nullable=False)
    diff: Mapped[str] = mapped_column(Text, default="", nullable=False)
    additions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    workflow: Mapped[WorkflowExecution] = relationship(back_populates="file_changes")


class TestExecutionResult(TimestampMixin, Base):
    __tablename__ = "test_results"
    __test__ = False  # not a pytest test class

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # passed | failed | not_run | error
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    commands: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    failures: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    coverage_notes: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    workflow: Mapped[WorkflowExecution] = relationship(back_populates="test_results")


class CodeReviewReport(TimestampMixin, Base):
    __tablename__ = "code_review_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    issues: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    automated_findings: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    diff_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_model: Mapped[str] = mapped_column(String(200), default="", nullable=False)

    workflow: Mapped[WorkflowExecution] = relationship(back_populates="review_reports")


class PullRequest(TimestampMixin, Base):
    __tablename__ = "pull_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(400), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    head_branch: Mapped[str] = mapped_column(String(300), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    draft: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    merged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    workflow: Mapped[WorkflowExecution] = relationship(back_populates="pull_request")
