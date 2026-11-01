"""Domain exceptions shared across services, agents and API routes."""

from __future__ import annotations


class DevFlowError(Exception):
    """Base class for expected, user-presentable errors."""

    status_code: int = 400

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DevFlowError):
    status_code = 404


class ConflictError(DevFlowError):
    status_code = 409


class LLMError(DevFlowError):
    """The LLM provider failed or returned unusable output."""

    status_code = 502


class GitHubError(DevFlowError):
    status_code = 502

    def __init__(self, message: str, *, status: int | None = None, details: dict | None = None) -> None:
        super().__init__(message, details=details)
        self.github_status = status


class GitHubNotConnectedError(DevFlowError):
    status_code = 412


class RepositoryError(DevFlowError):
    """Git / workspace operation failed."""


class UnsafePathError(RepositoryError):
    """An agent attempted to touch a path outside of the allowed workspace."""


class SandboxError(DevFlowError):
    status_code = 503


class WorkflowCancelledError(DevFlowError):
    status_code = 409


class AgentTimeoutError(DevFlowError):
    status_code = 504
