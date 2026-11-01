"""Per-execution runtime: the services and persistence hooks available to nodes.

The runtime is rebuilt every time a workflow is started or resumed, so it can
hold live objects (HTTP clients, locks, secrets) that must never be stored in
the checkpointed :class:`ProjectState`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import Settings
from app.core.errors import GitHubNotConnectedError, WorkflowCancelledError
from app.services.execution_service import DockerSandbox
from app.services.github_service import GitHubService
from app.services.llm_service import LLMService
from app.services.repository_service import RepositoryService, Workspace


class WorkflowRecorder(Protocol):
    """Persistence and event hooks used by nodes (implemented in workflow_service)."""

    def log(self, message: str, *, level: str = "info", agent: str | None = None,
            data: dict[str, Any] | None = None) -> None: ...
    def is_cancel_requested(self) -> bool: ...
    def start_agent(self, agent: str, node: str) -> str: ...
    def finish_agent(self, execution_id: str, *, status: str, output: dict | None = None,
                     error: str | None = None) -> None: ...
    def update_workflow(self, **fields: Any) -> None: ...
    def save_tasks(self, tasks: list[dict[str, Any]]) -> None: ...
    def save_file_changes(self, changes: list[dict[str, Any]]) -> None: ...
    def approve_file_changes(self, paths: list[str]) -> None: ...
    def save_test_result(self, report: dict[str, Any], attempt: int) -> None: ...
    def save_review(self, report: dict[str, Any], attempt: int) -> None: ...
    def save_pull_request(self, data: dict[str, Any]) -> None: ...


@dataclass
class WorkflowRuntime:
    workflow_id: str
    user_id: str
    settings: Settings
    llm: LLMService
    repositories: RepositoryService
    sandbox: DockerSandbox
    recorder: WorkflowRecorder
    token_provider: Callable[[], str | None]
    github_factory: Callable[[str], GitHubService] = GitHubService
    create_draft_pull_requests: bool = False
    require_execution_approval: bool = True
    require_release_approval: bool = True
    write_lock: threading.Lock = field(default_factory=threading.Lock)

    def workspace(self) -> Workspace:
        return self.repositories.open(self.workflow_id)

    def github(self) -> GitHubService:
        token = self.token_provider()
        if not token:
            raise GitHubNotConnectedError("GitHub is not connected. Add a token in Settings.")
        return self.github_factory(token)

    def check_cancelled(self) -> None:
        if self.recorder.is_cancel_requested():
            raise WorkflowCancelledError("Workflow cancelled by user")
