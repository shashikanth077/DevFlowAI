from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AGENT_NAMES = (
    "requirement_analyst", "repository_analyst", "architect", "task_orchestrator",
    "frontend_developer", "backend_developer", "qa_engineer", "code_reviewer", "release_engineer",
)


class SettingsOut(BaseModel):
    llm_provider: Literal["anthropic", "openai", "mistral"]
    llm_model: str
    llm_temperature: float
    llm_base_url: str | None
    llm_api_key_configured: bool
    agent_models: dict[str, str]
    workflow_max_retries: int
    require_execution_approval: bool
    require_release_approval: bool
    sandbox_allow_network_for_install: bool
    create_draft_pull_requests: bool
    mcp_enabled: bool = False
    mcp_disabled_servers: list[str] = Field(default_factory=list)
    available_agents: list[str] = Field(default_factory=lambda: list(AGENT_NAMES))


class SettingsUpdate(BaseModel):
    llm_provider: Literal["anthropic", "openai", "mistral"] | None = None
    llm_model: str | None = Field(default=None, min_length=1, max_length=200)
    llm_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    llm_base_url: str | None = Field(default=None, max_length=500)
    llm_api_key: str | None = Field(default=None, max_length=1000, description="Write-only; empty string clears it")
    agent_models: dict[str, str] | None = None
    workflow_max_retries: int | None = Field(default=None, ge=0, le=10)
    require_execution_approval: bool | None = None
    require_release_approval: bool | None = None
    sandbox_allow_network_for_install: bool | None = None
    create_draft_pull_requests: bool | None = None
    mcp_enabled: bool | None = None
    mcp_disabled_servers: list[str] | None = None


class LLMTestResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    message: str
    available_models: list[str] = Field(default_factory=list)
