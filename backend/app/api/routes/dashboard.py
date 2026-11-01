from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.workflows import workflow_summary
from app.database.session import get_db
from app.models import Project, PullRequest, User, WorkflowExecution
from app.schemas.workflow import DashboardStats, PullRequestOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DashboardStats:
    def count_status(*statuses: str) -> int:
        return db.scalar(select(func.count()).select_from(WorkflowExecution).where(
            WorkflowExecution.user_id == user.id, WorkflowExecution.status.in_(statuses))) or 0

    prs = db.query(PullRequest).filter_by(user_id=user.id).order_by(PullRequest.created_at.desc()).limit(5).all()
    recent = (db.query(WorkflowExecution).filter_by(user_id=user.id)
              .order_by(WorkflowExecution.created_at.desc()).limit(8).all())
    return DashboardStats(
        total_projects=db.scalar(select(func.count()).select_from(Project).where(Project.user_id == user.id)) or 0,
        active_workflows=count_status("queued", "running", "awaiting_approval"),
        successful_workflows=count_status("completed"),
        failed_workflows=count_status("failed"),
        awaiting_approval=count_status("awaiting_approval"),
        recent_pull_requests=[PullRequestOut.model_validate(p) for p in prs],
        recent_workflows=[workflow_summary(w) for w in recent],
    )
