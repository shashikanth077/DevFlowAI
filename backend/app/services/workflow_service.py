"""Workflow execution manager: persistence, background execution, approvals,
cancellation and checkpoint recovery."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, DevFlowError, NotFoundError
from app.database.connection import utcnow
from app.database.session import session_scope
from app.mcp_tools.broker import McpToolBroker
from app.mcp_tools.config import resolve_specs
from app.models import (
    AgentExecution,
    CodeReviewReport,
    DevelopmentTask,
    FileChange,
    Project,
    PullRequest,
    TestExecutionResult,
    ToolCall,
    WorkflowExecution,
    WorkflowLog,
)
from app.observability.tracing import get_tracing
from app.orchestration.checkpointing import get_checkpointer
from app.orchestration.graph import compile_graph
from app.orchestration.runtime import WorkflowRuntime
from app.orchestration.state import ProjectState
from app.services.execution_service import DockerSandbox
from app.services.llm_service import LLMService
from app.services.repository_service import RepositoryService
from app.services.settings_service import get_or_create_settings, github_token_for, llm_config_for

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class DBRecorder:
    """Implements :class:`WorkflowRecorder` on top of the relational database."""

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id

    def log(self, message: str, *, level: str = "info", agent: str | None = None,
            data: dict[str, Any] | None = None) -> None:
        logger.log(logging.WARNING if level == "warning" else logging.ERROR if level == "error" else logging.INFO,
                   message, extra={"workflow_id": self.workflow_id, "agent": agent})
        with session_scope() as db:
            db.add(WorkflowLog(workflow_id=self.workflow_id, level=level, agent=agent, message=message[:10_000],
                               data=data))

    def is_cancel_requested(self) -> bool:
        with session_scope() as db:
            return bool(db.scalar(select(WorkflowExecution.cancel_requested).where(
                WorkflowExecution.id == self.workflow_id)))

    def start_agent(self, agent: str, node: str) -> str:
        with session_scope() as db:
            attempt = db.scalar(select(func.count()).select_from(AgentExecution).where(
                AgentExecution.workflow_id == self.workflow_id, AgentExecution.node == node)) or 0
            row = AgentExecution(workflow_id=self.workflow_id, agent_name=agent, node=node, attempt=attempt + 1,
                                 status="running")
            db.add(row)
            db.flush()
            execution_id = row.id
        self.log(f"{agent} started ({node}, attempt {attempt + 1})", agent=agent)
        return execution_id

    def finish_agent(self, execution_id: str, *, status: str, output: dict | None = None,
                     error: str | None = None) -> None:
        with session_scope() as db:
            row = db.get(AgentExecution, execution_id)
            if row is None:
                return
            row.status = status
            row.finished_at = utcnow()
            started = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=row.finished_at.tzinfo)
            row.duration_ms = int((row.finished_at - started).total_seconds() * 1000)
            row.output = output
            row.error = error
            agent = row.agent_name
        if status == "completed":
            self.log(f"{agent} completed", agent=agent)

    def update_workflow(self, **fields: Any) -> None:
        with session_scope() as db:
            row = db.get(WorkflowExecution, self.workflow_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)

    def save_tasks(self, tasks: list[dict[str, Any]]) -> None:
        with session_scope() as db:
            existing = {t.task_key: t for t in db.scalars(select(DevelopmentTask).where(
                DevelopmentTask.workflow_id == self.workflow_id))}
            for task in tasks:
                if task.get("__replace__"):
                    continue
                row = existing.get(task["id"])
                if row is None:
                    row = DevelopmentTask(workflow_id=self.workflow_id, task_key=task["id"])
                    db.add(row)
                    existing[task["id"]] = row
                row.position = task.get("position", row.position or 0)
                row.title = task.get("title", row.title)
                row.description = task.get("description", row.description or "")
                row.assigned_agent = task.get("assigned_agent", row.assigned_agent)
                row.status = task.get("status", row.status or "pending")
                row.dependencies = task.get("dependencies", row.dependencies or [])
                row.target_files = task.get("target_files", row.target_files or [])
                row.acceptance_criteria = task.get("acceptance_criteria", row.acceptance_criteria or [])
                row.attempts = task.get("attempts", row.attempts or 0)
                row.notes = task.get("notes", row.notes or "")

    def save_file_changes(self, changes: list[dict[str, Any]]) -> None:
        with session_scope() as db:
            db.query(FileChange).filter_by(workflow_id=self.workflow_id).delete()
            for change in changes:
                db.add(FileChange(
                    workflow_id=self.workflow_id, path=change["path"], change_type=change["change_type"],
                    agent=change.get("agent", "unknown"), diff=change.get("diff", ""),
                    additions=change.get("additions", 0), deletions=change.get("deletions", 0),
                ))

    def approve_file_changes(self, paths: list[str]) -> None:
        with session_scope() as db:
            for row in db.scalars(select(FileChange).where(FileChange.workflow_id == self.workflow_id)):
                row.approved = row.path in paths

    def save_test_result(self, report: dict[str, Any], attempt: int) -> None:
        with session_scope() as db:
            db.add(TestExecutionResult(
                workflow_id=self.workflow_id, attempt=attempt, status=report["status"], summary=report["summary"],
                commands=report.get("commands", []), failures=report.get("failures", []),
                coverage_notes=report.get("coverage_notes", []), duration_ms=report.get("duration_ms", 0),
            ))

    def save_review(self, report: dict[str, Any], attempt: int) -> None:
        with session_scope() as db:
            db.add(CodeReviewReport(
                workflow_id=self.workflow_id, attempt=attempt, approved=report["approved"],
                summary=report["summary"], issues=report.get("issues", []),
                automated_findings=report.get("automated_findings", []), diff_hash=report["diff_hash"],
                reviewer_model=report.get("reviewer_model", ""),
            ))

    def save_pull_request(self, data: dict[str, Any]) -> None:
        with session_scope() as db:
            workflow = db.get(WorkflowExecution, self.workflow_id)
            assert workflow is not None
            db.add(PullRequest(workflow_id=self.workflow_id, user_id=workflow.user_id, **data))

    def save_tool_call(self, call: dict[str, Any]) -> None:
        with session_scope() as db:
            db.add(ToolCall(workflow_id=self.workflow_id, **call))

    def add_trace_run(self, run_id: str) -> None:
        with session_scope() as db:
            row = db.get(WorkflowExecution, self.workflow_id)
            if row is not None:
                row.trace_run_ids = [*(row.trace_run_ids or []), run_id]


RuntimeFactory = Callable[[str], WorkflowRuntime]


def default_runtime_factory(workflow_id: str) -> WorkflowRuntime:
    settings = get_settings()
    with session_scope() as db:
        workflow = db.get(WorkflowExecution, workflow_id)
        if workflow is None:
            raise NotFoundError("Workflow not found")
        user_id = workflow.user_id
        prefs = get_or_create_settings(db, user_id)
        llm_config = llm_config_for(prefs)
        allow_network = prefs.sandbox_allow_network_for_install
        draft = prefs.create_draft_pull_requests
        exec_approval = prefs.require_execution_approval
        release_approval = prefs.require_release_approval
        use_mcp = settings.mcp_enabled and prefs.mcp_enabled
        disabled_mcp = set(prefs.mcp_disabled_servers or [])

    def token_provider() -> str | None:
        with session_scope() as db:
            return github_token_for(db, user_id)

    repositories = RepositoryService(settings)
    recorder = DBRecorder(workflow_id)
    broker = None
    if use_mcp:
        specs, errors = resolve_specs(settings, repositories.workspace_dir(workflow_id) / "repo")
        for error in errors:
            recorder.log(f"MCP configuration: {error}", level="warning")
        if specs:
            broker = McpToolBroker(specs, settings, recorder, disabled_servers=disabled_mcp)
    return WorkflowRuntime(
        workflow_id=workflow_id, user_id=user_id, settings=settings, llm=LLMService(llm_config),
        repositories=repositories,
        sandbox=DockerSandbox(settings, allow_network_for_install=allow_network),
        recorder=recorder, token_provider=token_provider,
        create_draft_pull_requests=draft, require_execution_approval=exec_approval,
        require_release_approval=release_approval, mcp=broker,
    )


def initial_state(workflow: WorkflowExecution, project: Project) -> ProjectState:
    repo = project.repository
    return ProjectState(
        project_id=project.id, workflow_id=workflow.id, user_id=workflow.user_id,
        repository_full_name=repo.full_name, repository_url=repo.clone_url, base_branch=workflow.base_branch,
        user_requirement=workflow.requirement, development_tasks=[], generated_files=[], modified_files=[],
        file_ownership={}, agent_summaries={}, active_agents=[], fix_feedback={}, workflow_status="running",
        retry_count=0, max_retries=workflow.max_retries, execution_approved=False, release_approved=False,
    )


class WorkflowManager:
    def __init__(self, settings: Settings | None = None, runtime_factory: RuntimeFactory | None = None,
                 checkpointer=None) -> None:
        self.settings = settings or get_settings()
        self.runtime_factory = runtime_factory or default_runtime_factory
        self._checkpointer = checkpointer
        self._executor = ThreadPoolExecutor(max_workers=self.settings.workflow_worker_threads,
                                            thread_name_prefix="workflow")
        self._active: dict[str, Future] = {}
        self._lock = threading.Lock()

    @property
    def checkpointer(self):
        if self._checkpointer is None:
            self._checkpointer = get_checkpointer(self.settings)
        return self._checkpointer

    @staticmethod
    def _config(workflow_id: str) -> dict:
        return {"configurable": {"thread_id": workflow_id}, "recursion_limit": 200}

    # -- public operations ---------------------------------------------------------------

    def start(self, db: Session, *, user_id: str, project: Project, requirement: str,
              base_branch: str | None) -> WorkflowExecution:
        prefs = get_or_create_settings(db, user_id)
        workflow = WorkflowExecution(
            project_id=project.id, user_id=user_id, requirement=requirement.strip(),
            base_branch=base_branch or project.base_branch, status="queued",
            max_retries=prefs.workflow_max_retries, started_at=utcnow(),
        )
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        state = initial_state(workflow, project)
        self.submit(workflow.id, state)
        return workflow

    def approve(self, db: Session, workflow: WorkflowExecution, *, approved: bool, comment: str,
                user_id: str) -> WorkflowExecution:
        if workflow.status != "awaiting_approval" or not workflow.pending_approval:
            raise ConflictError(f"Workflow is not awaiting approval (status: {workflow.status})")
        gate = workflow.pending_approval.get("gate")
        workflow.approvals = [*workflow.approvals, {
            "gate": gate, "approved": approved, "comment": comment, "user_id": user_id,
            "at": utcnow().isoformat(),
        }]
        workflow.pending_approval = None
        workflow.status = "running"
        last_run = (workflow.trace_run_ids or [None])[-1]
        db.commit()
        get_tracing().feedback(last_run, f"human_approval_{gate}", 1.0 if approved else 0.0, comment or None)
        self.submit(workflow.id, Command(resume={"approved": approved, "comment": comment}))
        return workflow

    def cancel(self, db: Session, workflow: WorkflowExecution) -> WorkflowExecution:
        if workflow.status in TERMINAL_STATUSES:
            raise ConflictError(f"Workflow already {workflow.status}")
        workflow.cancel_requested = True
        if workflow.status in ("awaiting_approval", "queued") and not self.is_active(workflow.id):
            workflow.status = "cancelled"
            workflow.pending_approval = None
            workflow.completed_at = utcnow()
            db.add(WorkflowLog(workflow_id=workflow.id, level="warning", agent="human",
                               message="Workflow cancelled by user"))
            self._cleanup(workflow.id)
        db.commit()
        return workflow

    def is_active(self, workflow_id: str) -> bool:
        with self._lock:
            future = self._active.get(workflow_id)
            return future is not None and not future.done()

    def submit(self, workflow_id: str, payload: Any) -> Future:
        with self._lock:
            current = self._active.get(workflow_id)
            if current is not None and not current.done():
                raise ConflictError("Workflow is already executing")
            future = self._executor.submit(self._execute, workflow_id, payload)
            self._active[workflow_id] = future
            return future

    def wait(self, workflow_id: str, timeout: float | None = None) -> None:
        with self._lock:
            future = self._active.get(workflow_id)
        if future is not None:
            future.result(timeout=timeout)

    def resume_interrupted(self) -> list[str]:
        """Resume workflows left running by a previous process from their last checkpoint."""
        resumed: list[str] = []
        with session_scope() as db:
            rows = db.scalars(select(WorkflowExecution).where(
                WorkflowExecution.status.in_(["queued", "running"]))).all()
            pending = [(w.id, initial_state(w, w.project)) for w in rows]
        for workflow_id, state in pending:
            try:
                snapshot = self._graph_for_snapshot(workflow_id).get_state(self._config(workflow_id))
                payload = None if snapshot.values else state
                DBRecorder(workflow_id).log("Resuming workflow from last checkpoint after restart",
                                            level="warning", agent="task_orchestrator")
                self.submit(workflow_id, payload)
                resumed.append(workflow_id)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to resume workflow", extra={"workflow_id": workflow_id})
        return resumed

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- execution ------------------------------------------------------------------------

    def _graph_for_snapshot(self, workflow_id: str):
        return compile_graph(self.runtime_factory(workflow_id), self.checkpointer)

    def _execute(self, workflow_id: str, payload: Any) -> None:
        recorder = DBRecorder(workflow_id)
        config = self._config(workflow_id)
        tracing = get_tracing()
        run_id: str | None = None
        runtime = None
        try:
            runtime = self.runtime_factory(workflow_id)
            graph = compile_graph(runtime, self.checkpointer)
            recorder.update_workflow(status="running")
            traced_config, run_id = tracing.run_config(
                config, workflow_id=workflow_id, metadata=self._trace_metadata(workflow_id, runtime),
                resumed=payload is None or isinstance(payload, Command),
            )
            if run_id:
                recorder.add_trace_run(run_id)
            graph.invoke(payload, traced_config)
            snapshot = graph.get_state(config)
        except Exception as exc:  # noqa: BLE001
            message = exc.message if isinstance(exc, DevFlowError) else f"{type(exc).__name__}: {exc}"
            logger.exception("Workflow execution crashed", extra={"workflow_id": workflow_id})
            recorder.log(f"Workflow failed: {message}", level="error", agent="task_orchestrator")
            recorder.update_workflow(status="failed", error_details={"message": message, "type": type(exc).__name__},
                                     completed_at=utcnow())
            tracing.feedback(run_id, "workflow_completed", 0.0, message[:300])
            self._cleanup(workflow_id)
            return
        finally:
            if runtime is not None:
                runtime.close()
            tracing.flush()

        interrupts = list(getattr(snapshot, "interrupts", ()) or [])
        if interrupts:
            approval = interrupts[0].value
            recorder.update_workflow(status="awaiting_approval", pending_approval=approval,
                                     current_stage="execution_approval" if approval.get("gate") == "execution"
                                     else "release_approval")
            recorder.log(f"Waiting for human approval: {approval.get('title')}", level="info", agent="human")
            return

        values = snapshot.values or {}
        status = values.get("workflow_status")
        if status not in TERMINAL_STATUSES:
            status = "failed"
            values.setdefault("error_details", {"message": "Workflow ended without reaching a terminal state"})
        fields: dict[str, Any] = {"status": status, "completed_at": utcnow(), "pending_approval": None}
        for key in ("feature_branch", "commit_id", "pull_request_url", "error_details", "retry_count"):
            if values.get(key) is not None:
                fields[key] = values[key]
        if status == "completed":
            fields["current_stage"] = "completed"
        recorder.update_workflow(**fields)
        recorder.log(f"Workflow {status}", level="info" if status == "completed" else "warning",
                     agent="task_orchestrator")
        self._report_outcome(tracing, run_id, status, values)
        tracing.flush()
        self._cleanup(workflow_id)

    def _trace_metadata(self, workflow_id: str, runtime: WorkflowRuntime) -> dict[str, Any]:
        with session_scope() as db:
            workflow = db.get(WorkflowExecution, workflow_id)
            project = workflow.project if workflow else None
            meta: dict[str, Any] = {
                "project_id": workflow.project_id if workflow else None,
                "project_name": project.name if project else None,
                "repository": project.repository.full_name if project else None,
                "base_branch": workflow.base_branch if workflow else None,
                "max_retries": workflow.max_retries if workflow else None,
            }
        meta.update(user_id=runtime.user_id, llm_provider=runtime.llm.config.provider,
                    llm_model=runtime.llm.config.model, mcp_enabled=runtime.mcp is not None,
                    environment=self.settings.environment)
        return meta

    @staticmethod
    def _report_outcome(tracing, run_id: str | None, status: str, values: dict[str, Any]) -> None:
        """Send the workflow's quality signals to LangSmith as feedback on the final trace segment."""
        tests = (values.get("test_results") or {}).get("status")
        if tests:
            tracing.feedback(run_id, "tests_passed", 1.0 if tests == "passed" else 0.0, tests)
        review = values.get("review_feedback") or {}
        if "approved" in review:
            tracing.feedback(run_id, "review_approved", 1.0 if review["approved"] else 0.0, review.get("summary"))
        tracing.feedback(run_id, "workflow_completed", 1.0 if status == "completed" else 0.0, status)
        tracing.feedback(run_id, "retries_used", None, value=values.get("retry_count", 0))

    def _cleanup(self, workflow_id: str) -> None:
        if self.settings.cleanup_workspaces:
            RepositoryService(self.settings).cleanup(workflow_id)


_manager: WorkflowManager | None = None


def get_workflow_manager() -> WorkflowManager:
    global _manager
    if _manager is None:
        _manager = WorkflowManager()
    return _manager


def set_workflow_manager(manager: WorkflowManager | None) -> None:
    global _manager
    _manager = manager
