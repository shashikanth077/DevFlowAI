"""LangGraph node implementations.

Each node is a thin adapter between :class:`ProjectState` and an agent. The
``tracked`` wrapper adds the cross-cutting concerns every agent needs:
cancellation checks, an agent execution record, structured logging, a hard
timeout and conversion of failures into state (never silently ignored).
"""

from __future__ import annotations

import contextvars
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt

from app.agents.architecture_agent import ArchitectureAgent
from app.agents.backend_agent import BackendDevelopmentAgent
from app.agents.frontend_agent import FrontendDevelopmentAgent
from app.agents.github_agent import GitHubReleaseAgent, branch_name_for
from app.agents.repository_agent import RepositoryAnalystAgent
from app.agents.requirement_agent import RequirementAnalystAgent
from app.agents.review_agent import CodeReviewAgent, feedback_from_review
from app.agents.task_agent import TaskOrchestratorAgent
from app.agents.testing_agent import TestingAgent, feedback_from_report
from app.core.errors import AgentTimeoutError, DevFlowError, WorkflowCancelledError
from app.orchestration.runtime import WorkflowRuntime
from app.orchestration.state import ProjectState

logger = logging.getLogger(__name__)

NodeFn = Callable[[ProjectState], dict[str, Any]]

AGENT_FOR_NODE = {
    "requirement_analysis": "requirement_analyst",
    "repository_analysis": "repository_analyst",
    "architecture_design": "architect",
    "task_planning": "task_orchestrator",
    "frontend_development": "frontend_developer",
    "backend_development": "backend_developer",
    "development_join": "task_orchestrator",
    "execution_approval": "human",
    "testing": "qa_engineer",
    "code_review": "code_reviewer",
    "release_approval": "human",
    "github_release": "release_engineer",
    "max_retries_exceeded": "task_orchestrator",
}

# Fields mirrored from state into the workflow DB row after every node.
_MIRRORED = ("requirement_analysis", "repository_analysis", "architecture_plan", "retry_count",
             "feature_branch", "commit_id", "pull_request_url", "error_details")


def _summarise(update: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in update.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value if not isinstance(value, str) else value[:500]
        elif isinstance(value, list):
            out[key] = f"{len(value)} items"
        elif isinstance(value, dict):
            out[key] = f"{len(value)} keys"
    return out


def tracked(runtime: WorkflowRuntime, node: str, fn: NodeFn, *, timeout: bool = True) -> NodeFn:
    agent = AGENT_FOR_NODE[node]
    recorder = runtime.recorder

    def wrapper(state: ProjectState) -> dict[str, Any]:
        if state.get("workflow_status") in ("cancelled", "failed"):
            return {}
        if recorder.is_cancel_requested():
            recorder.log("Cancellation requested; stopping before " + node, level="warning", agent=agent)
            return {"workflow_status": "cancelled"}
        recorder.update_workflow(status="running", current_stage=node)
        human_gate = agent == "human"
        execution_id = None if human_gate else recorder.start_agent(agent, node)
        started = time.monotonic()
        try:
            if timeout:
                ctx = contextvars.copy_context()
                pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"agent-{node}")
                future = pool.submit(ctx.run, fn, state)
                try:
                    update = future.result(timeout=runtime.settings.agent_timeout_seconds)
                except FutureTimeout as exc:
                    raise AgentTimeoutError(
                        f"{agent} exceeded the {runtime.settings.agent_timeout_seconds}s timeout"
                    ) from exc
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)
            else:
                update = fn(state)
        except GraphBubbleUp:
            raise  # interrupt() for a human approval gate - handled by the workflow runner
        except WorkflowCancelledError:
            if execution_id:
                recorder.finish_agent(execution_id, status="cancelled")
            recorder.log("Workflow cancelled", level="warning", agent=agent)
            return {"workflow_status": "cancelled"}
        except Exception as exc:  # noqa: BLE001 - every failure is recorded and surfaced
            execution_id = execution_id or recorder.start_agent(agent, node)
            message = exc.message if isinstance(exc, DevFlowError) else f"{type(exc).__name__}: {exc}"
            logger.exception("Node failed", extra={"node": node, "workflow_id": runtime.workflow_id})
            recorder.finish_agent(execution_id, status="failed", error=message)
            recorder.log(f"{agent} failed: {message}", level="error", agent=agent)
            details = {"node": node, "agent": agent, "message": message,
                       "type": type(exc).__name__, **(getattr(exc, "details", None) or {})}
            recorder.update_workflow(error_details=details)
            return {"workflow_status": "failed", "error_details": details}
        duration = int((time.monotonic() - started) * 1000)
        if human_gate and not update:
            return update  # gate skipped (approval not required or already given)
        execution_id = execution_id or recorder.start_agent(agent, node)
        status = "completed" if update.get("workflow_status") != "cancelled" else "rejected"
        recorder.finish_agent(execution_id, status=status, output=_summarise(update))
        mirrored = {k: update[k] for k in _MIRRORED if k in update}
        if mirrored:
            recorder.update_workflow(**mirrored)
        logger.info("Node completed", extra={"node": node, "duration_ms": duration, "workflow_id": runtime.workflow_id})
        return update

    wrapper.__name__ = node
    return wrapper


def build_nodes(rt: WorkflowRuntime) -> dict[str, NodeFn]:
    def requirement_analysis(state: ProjectState) -> dict[str, Any]:
        analysis = RequirementAnalystAgent(rt).run(state["user_requirement"], state.get("repository_full_name", ""))
        return {
            "requirement_analysis": analysis.model_dump(),
            "acceptance_criteria": analysis.acceptance_criteria,
            "workflow_status": "running",
        }

    def repository_analysis(state: ProjectState) -> dict[str, Any]:
        analysis, path = RepositoryAnalystAgent(rt).run(
            clone_url=state["repository_url"], base_branch=state["base_branch"],
            requirement_analysis=state["requirement_analysis"],
        )
        return {"repository_analysis": analysis.model_dump(), "repository_path": path}

    def architecture_design(state: ProjectState) -> dict[str, Any]:
        return {"architecture_plan": ArchitectureAgent(rt).run(dict(state)).model_dump()}

    def task_planning(state: ProjectState) -> dict[str, Any]:
        tasks = [t.model_dump() for t in TaskOrchestratorAgent(rt).run(dict(state))]
        rt.recorder.save_tasks(tasks)
        roles = sorted({t["assigned_agent"] for t in tasks})
        title = state["requirement_analysis"].get("title") or state["user_requirement"][:60]
        return {
            "development_tasks": [{"id": "_", "__replace__": True}, *tasks],
            "active_agents": roles,
            "fix_feedback": {},
            "feature_branch": branch_name_for(title, state["workflow_id"]),
        }

    def frontend_development(state: ProjectState) -> dict[str, Any]:
        return FrontendDevelopmentAgent(rt).run(dict(state))

    def backend_development(state: ProjectState) -> dict[str, Any]:
        return BackendDevelopmentAgent(rt).run(dict(state))

    def development_join(state: ProjectState) -> dict[str, Any]:
        """Integrate parallel development results: persist the real git diff per file."""
        ws = rt.workspace()
        changes = ws.changed_files()
        stats = ws.numstat()
        ownership = state.get("file_ownership", {})
        records = []
        for change in changes:
            added, deleted = stats.get(change["path"], (0, 0))
            records.append({
                **change, "agent": ownership.get(change["path"], "unknown"),
                "diff": ws.diff([change["path"]]), "additions": added, "deletions": deleted,
            })
        rt.recorder.save_file_changes(records)
        rt.recorder.save_tasks(state.get("development_tasks", []))
        rt.recorder.log(f"Integrated {len(records)} changed files", agent="task_orchestrator")
        if not records:
            raise DevFlowError("Development finished without any file changes")
        return {
            "generated_files": [c["path"] for c in changes if c["change_type"] == "created"],
            "modified_files": [c["path"] for c in changes if c["change_type"] == "modified"],
            "fix_feedback": {},
        }

    def execution_approval(state: ProjectState) -> dict[str, Any]:
        if not rt.require_execution_approval or state.get("execution_approved"):
            return {}
        plans = TestingAgent(rt).plan_commands(dict(state))
        decision = interrupt({
            "gate": "execution",
            "title": "Approve execution of generated code in the sandbox",
            "description": "QA will install dependencies and run these commands inside an isolated Docker "
                           "container (no host mounts, resource limits, network disabled for tests).",
            "commands": plans,
            "changed_files": list(state.get("generated_files", [])) + list(state.get("modified_files", [])),
            "network_for_install": rt.sandbox.allow_network_for_install,
        })
        if not decision or not decision.get("approved"):
            rt.recorder.log("Execution rejected by user", level="warning", agent="human")
            return {"workflow_status": "cancelled", "error_details": {"message": "Execution approval rejected",
                                                                       "comment": (decision or {}).get("comment", "")}}
        rt.recorder.log("Sandbox execution approved", agent="human", data={"comment": decision.get("comment", "")})
        return {"execution_approved": True, "approval_comment": decision.get("comment", "")}

    def testing(state: ProjectState) -> dict[str, Any]:
        report = TestingAgent(rt).run(dict(state))
        attempt = state.get("retry_count", 0) + 1
        rt.recorder.save_test_result(report.model_dump(), attempt)
        update: dict[str, Any] = {"test_results": report.model_dump()}
        if report.status == "failed":
            feedback = feedback_from_report(report, state.get("file_ownership", {}))
            update |= _correction(state, feedback, "tests_failed", "Tests failed")
        else:
            update["workflow_status"] = "running"
        return update

    def code_review(state: ProjectState) -> dict[str, Any]:
        report = CodeReviewAgent(rt).run(dict(state))
        attempt = state.get("retry_count", 0) + 1
        rt.recorder.save_review(report.model_dump(), attempt)
        update: dict[str, Any] = {"review_feedback": report.model_dump()}
        if report.approved:
            update |= {"workflow_status": "running", "approved_diff_hash": report.diff_hash}
        else:
            update |= _correction(state, feedback_from_review(report), "review_failed", "Review rejected changes")
        return update

    def _correction(state: ProjectState, feedback: dict[str, list[str]], status: str, label: str) -> dict[str, Any]:
        retry = state.get("retry_count", 0)
        max_retries = state.get("max_retries", rt.settings.workflow_max_retries)
        if retry >= max_retries:
            return {"workflow_status": status, "retry_count": retry + 1, "fix_feedback": feedback,
                    "active_agents": sorted(feedback)}
        tasks = [
            {**t, "status": "needs_fix"} for t in state.get("development_tasks", []) if t["assigned_agent"] in feedback
        ]
        rt.recorder.save_tasks(tasks)
        rt.recorder.log(f"{label}; routing feedback to {', '.join(sorted(feedback))} (retry {retry + 1}/{max_retries})",
                        level="warning", agent="task_orchestrator")
        return {"workflow_status": status, "retry_count": retry + 1, "fix_feedback": feedback,
                "active_agents": sorted(feedback), "development_tasks": tasks}

    def max_retries_exceeded(state: ProjectState) -> dict[str, Any]:
        reason = "tests" if state.get("workflow_status") == "tests_failed" else "code review"
        details = {
            "message": f"Maximum retries ({state.get('max_retries')}) reached; {reason} still failing.",
            "node": "max_retries_exceeded",
            "feedback": state.get("fix_feedback", {}),
        }
        rt.recorder.save_tasks([{**t, "status": "failed"} for t in state.get("development_tasks", [])
                                if t["status"] == "needs_fix"])
        rt.recorder.log(details["message"], level="error", agent="task_orchestrator")
        return {"workflow_status": "failed", "error_details": details}

    def release_approval(state: ProjectState) -> dict[str, Any]:
        if not rt.require_release_approval or state.get("release_approved"):
            return {"release_approved": True}
        tests = state.get("test_results", {})
        review = state.get("review_feedback", {})
        decision = interrupt({
            "gate": "release",
            "title": "Approve push to GitHub and pull request creation",
            "description": "The release agent will create the feature branch, commit the approved files, push "
                           "the branch and open a pull request. Nothing is merged automatically.",
            "repository": state.get("repository_full_name"),
            "base_branch": state.get("base_branch"),
            "feature_branch": state.get("feature_branch"),
            "files": list(state.get("generated_files", [])) + list(state.get("modified_files", [])),
            "test_status": tests.get("status"),
            "test_summary": tests.get("summary"),
            "review_approved": review.get("approved"),
            "review_summary": review.get("summary"),
        })
        if not decision or not decision.get("approved"):
            rt.recorder.log("Release rejected by user", level="warning", agent="human")
            return {"workflow_status": "cancelled", "error_details": {"message": "Release approval rejected",
                                                                       "comment": (decision or {}).get("comment", "")}}
        rt.recorder.log("Release approved", agent="human", data={"comment": decision.get("comment", "")})
        return {"release_approved": True, "approval_comment": decision.get("comment", "")}

    def github_release(state: ProjectState) -> dict[str, Any]:
        result = GitHubReleaseAgent(rt).run(dict(state))
        return {**result, "workflow_status": "completed"}

    raw: dict[str, tuple[NodeFn, bool]] = {
        "requirement_analysis": (requirement_analysis, True),
        "repository_analysis": (repository_analysis, True),
        "architecture_design": (architecture_design, True),
        "task_planning": (task_planning, True),
        "frontend_development": (frontend_development, True),
        "backend_development": (backend_development, True),
        "development_join": (development_join, True),
        "execution_approval": (execution_approval, False),  # interrupt() must run in the graph thread
        "testing": (testing, True),
        "code_review": (code_review, True),
        "max_retries_exceeded": (max_retries_exceeded, True),
        "release_approval": (release_approval, False),
        "github_release": (github_release, True),
    }
    return {name: tracked(rt, name, fn, timeout=use_timeout) for name, (fn, use_timeout) in raw.items()}
