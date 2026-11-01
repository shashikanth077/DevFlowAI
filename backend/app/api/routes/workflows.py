from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_project, get_owned_workflow, get_stream_user
from app.database.session import get_db, session_factory
from app.models import Project, User, WorkflowExecution, WorkflowLog
from app.observability.tracing import get_tracing
from app.schemas.integrations import ToolCallOut, TraceInfo
from app.schemas.task import TaskOut
from app.schemas.workflow import (
    AgentExecutionOut,
    ApprovalRequest,
    FileChangeOut,
    PullRequestOut,
    ReviewReportOut,
    TestResultOut,
    WorkflowDetail,
    WorkflowLogOut,
    WorkflowResults,
    WorkflowStartRequest,
    WorkflowSummary,
)
from app.services.workflow_service import TERMINAL_STATUSES, get_workflow_manager

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def workflow_summary(w: WorkflowExecution) -> WorkflowSummary:
    return WorkflowSummary(
        id=w.id, project_id=w.project_id, project_name=w.project.name if w.project else "",
        repository_full_name=w.project.repository.full_name if w.project else "",
        requirement=w.requirement, base_branch=w.base_branch, feature_branch=w.feature_branch, status=w.status,
        current_stage=w.current_stage, retry_count=w.retry_count, pull_request_url=w.pull_request_url,
        created_at=w.created_at, completed_at=w.completed_at,
    )


def workflow_detail(w: WorkflowExecution) -> WorkflowDetail:
    base = workflow_summary(w).model_dump()
    return WorkflowDetail(
        **base, max_retries=w.max_retries, cancel_requested=w.cancel_requested,
        pending_approval=w.pending_approval, approvals=w.approvals or [],
        requirement_analysis=w.requirement_analysis, repository_analysis=w.repository_analysis,
        architecture_plan=w.architecture_plan, error_details=w.error_details, commit_id=w.commit_id,
        trace_run_ids=list(w.trace_run_ids or []),
        started_at=w.started_at,
        agent_executions=[AgentExecutionOut.model_validate(a) for a in w.agent_executions],
        tasks=[TaskOut.model_validate(t) for t in w.tasks],
    )


@router.post("/start", response_model=WorkflowDetail, status_code=status.HTTP_202_ACCEPTED)
def start_workflow(body: WorkflowStartRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project: Project = get_owned_project(body.project_id, db, user)
    workflow = get_workflow_manager().start(db, user_id=user.id, project=project, requirement=body.requirement,
                                            base_branch=body.base_branch)
    db.refresh(workflow)
    return workflow_detail(workflow)


@router.get("", response_model=list[WorkflowSummary])
def list_workflows(project_id: str | None = None, status_filter: str | None = Query(None, alias="status"),
                   limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    query = db.query(WorkflowExecution).filter_by(user_id=user.id)
    if project_id:
        query = query.filter_by(project_id=project_id)
    if status_filter:
        query = query.filter_by(status=status_filter)
    return [workflow_summary(w) for w in query.order_by(WorkflowExecution.created_at.desc()).limit(limit)]


@router.get("/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(workflow_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return workflow_detail(get_owned_workflow(workflow_id, db, user))


@router.post("/{workflow_id}/cancel", response_model=WorkflowDetail)
def cancel_workflow(workflow_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    workflow = get_workflow_manager().cancel(db, get_owned_workflow(workflow_id, db, user))
    db.refresh(workflow)
    return workflow_detail(workflow)


@router.post("/{workflow_id}/approve", response_model=WorkflowDetail)
def approve_workflow(workflow_id: str, body: ApprovalRequest, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    workflow = get_owned_workflow(workflow_id, db, user)
    workflow = get_workflow_manager().approve(db, workflow, approved=body.approved, comment=body.comment,
                                              user_id=user.id)
    db.refresh(workflow)
    return workflow_detail(workflow)


@router.get("/{workflow_id}/logs", response_model=list[WorkflowLogOut])
def workflow_logs(workflow_id: str, after_id: int = 0, limit: int = Query(500, ge=1, le=5000),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    get_owned_workflow(workflow_id, db, user)
    return db.scalars(select(WorkflowLog).where(WorkflowLog.workflow_id == workflow_id, WorkflowLog.id > after_id)
                      .order_by(WorkflowLog.id).limit(limit)).all()


@router.get("/{workflow_id}/results", response_model=WorkflowResults)
def workflow_results(workflow_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    w = get_owned_workflow(workflow_id, db, user)
    return WorkflowResults(
        workflow_id=w.id, status=w.status, feature_branch=w.feature_branch, commit_id=w.commit_id,
        pull_request_url=w.pull_request_url,
        file_changes=[FileChangeOut.model_validate(f) for f in sorted(w.file_changes, key=lambda f: f.path)],
        test_results=[TestResultOut.model_validate(t) for t in w.test_results],
        review_reports=[ReviewReportOut.model_validate(r) for r in w.review_reports],
        tool_calls=[ToolCallOut.model_validate(c) for c in w.tool_calls],
        pull_request=PullRequestOut.model_validate(w.pull_request) if w.pull_request else None,
    )


@router.get("/{workflow_id}/trace", response_model=TraceInfo)
def workflow_trace(workflow_id: str, resolve_urls: bool = False, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """LangSmith trace runs of this workflow (one root run per execution segment)."""
    w = get_owned_workflow(workflow_id, db, user)
    tracing = get_tracing()
    run_ids = list(w.trace_run_ids or [])
    urls = {rid: tracing.run_url(rid) for rid in run_ids} if resolve_urls else {}
    note = None if tracing.enabled else (
        "LangSmith tracing is disabled." + (" Runs below were traced earlier." if run_ids else ""))
    return TraceInfo(enabled=tracing.enabled, project=tracing.project, run_ids=run_ids, urls=urls, note=note)


@router.get("/{workflow_id}/events")
async def workflow_events(workflow_id: str, request: Request, user: User = Depends(get_stream_user)):
    """Server-Sent Events stream of logs and workflow snapshots."""
    with session_factory()() as db:
        get_owned_workflow(workflow_id, db, user)

    def poll(last_id: int) -> tuple[list[dict], dict, int]:
        with session_factory()() as db:
            logs = db.scalars(select(WorkflowLog).where(WorkflowLog.workflow_id == workflow_id,
                                                        WorkflowLog.id > last_id).order_by(WorkflowLog.id)
                              .limit(500)).all()
            workflow = db.get(WorkflowExecution, workflow_id)
            snapshot = workflow_detail(workflow).model_dump(mode="json") if workflow else {}
            new_last = logs[-1].id if logs else last_id
            return [WorkflowLogOut.model_validate(entry).model_dump(mode="json") for entry in logs], snapshot, new_last

    async def stream() -> AsyncIterator[str]:
        last_id = 0
        last_snapshot = ""
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                break
            logs, snapshot, last_id = await asyncio.to_thread(poll, last_id)
            for entry in logs:
                yield f"event: log\ndata: {json.dumps(entry)}\n\n"
            encoded = json.dumps(snapshot, sort_keys=True)
            if encoded != last_snapshot:
                last_snapshot = encoded
                yield f"event: workflow\ndata: {encoded}\n\n"
            if snapshot.get("status") in TERMINAL_STATUSES and not logs:
                yield "event: end\ndata: {}\n\n"
                break
            idle_ticks = 0 if logs else idle_ticks + 1
            if idle_ticks and idle_ticks % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
