from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import APIModel

_BRANCH_FORBIDDEN = (" ", "..", "~", "^", ":", "?", "*", "[", "\\", "@{")


def validate_branch_name(value: str) -> str:
    value = value.strip()
    if not value or any(token in value for token in _BRANCH_FORBIDDEN) or value.startswith(("-", "/")) or value.endswith((".lock", "/", ".")):
        raise ValueError("Invalid git branch name")
    return value


class RepositoryConnectRequest(BaseModel):
    full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", description="owner/name")


class RepositoryOut(APIModel):
    id: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool
    html_url: str
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    repository_id: str
    base_branch: str = Field(min_length=1, max_length=200)

    _branch = field_validator("base_branch")(validate_branch_name)


class ProjectOut(APIModel):
    id: str
    name: str
    description: str
    base_branch: str
    repository: RepositoryOut
    created_at: datetime
    workflow_count: int = 0
    last_workflow_status: str | None = None
