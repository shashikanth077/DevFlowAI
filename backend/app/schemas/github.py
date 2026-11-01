from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GitHubConnectRequest(BaseModel):
    token: str = Field(min_length=20, max_length=500, description="Personal access token (stored encrypted)")


class GitHubStatus(BaseModel):
    connected: bool
    login: str | None = None
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None = None
    source: str | None = None  # "user" | "server"


class GitHubRepo(BaseModel):
    full_name: str
    owner: str
    name: str
    private: bool
    default_branch: str
    html_url: str
    description: str | None = None
    updated_at: str | None = None


class GitHubBranch(BaseModel):
    name: str
    protected: bool
    sha: str


class PullRequestStatus(BaseModel):
    number: int
    url: str
    state: str
    merged: bool
    draft: bool
    mergeable_state: str | None = None
    title: str
