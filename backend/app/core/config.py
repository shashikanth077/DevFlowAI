"""Application configuration loaded from environment variables.

All secrets (database password, JWT secret, encryption key, GitHub token,
LLM API keys) come from the environment and are never hardcoded.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["ollama", "openai", "mistral"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # --- Application -----------------------------------------------------
    app_name: str = "DevFlow AI"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])

    # --- Security --------------------------------------------------------
    secret_key: str = Field(default="change-me-in-production-please-use-a-long-random-string", min_length=32)
    encryption_key: str | None = None  # Fernet key; derived from secret_key when omitted
    access_token_expire_minutes: int = 60 * 12
    password_hash_iterations: int = 310_000
    allow_registration: bool = True

    # --- Database --------------------------------------------------------
    database_url: str = "postgresql+psycopg://devflow:devflow@localhost:5432/devflow"
    db_echo: bool = False
    checkpoint_backend: Literal["auto", "postgres", "sqlite", "memory"] = "auto"
    checkpoint_sqlite_path: str = "./devflow_checkpoints.sqlite"

    # --- LLM ---------------------------------------------------------------
    llm_provider: LLMProviderName = "ollama"
    llm_model: str = "llama3.1:8b"
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 300.0
    llm_max_retries: int = 3
    llm_context_chars: int = 60_000
    ollama_base_url: str = "http://localhost:11434"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    mistral_base_url: str = "https://api.mistral.ai/v1"
    mistral_api_key: str | None = None

    # --- GitHub ------------------------------------------------------------
    github_api_url: str = "https://api.github.com"
    github_token: str | None = None  # optional server-wide fallback token
    github_timeout_seconds: float = 30.0
    protected_branch_patterns: list[str] = Field(
        default_factory=lambda: ["main", "master", "develop", "production", "release/*"]
    )
    git_author_name: str = "DevFlow AI"
    git_author_email: str = "devflow-ai@users.noreply.github.com"

    # --- Workspace & sandbox -----------------------------------------------
    workspace_root: Path = Path("./workspaces")
    cleanup_workspaces: bool = True
    max_file_bytes: int = 200_000
    sandbox_enabled: bool = True
    sandbox_cpus: float = 1.0
    sandbox_memory: str = "1g"
    sandbox_pids_limit: int = 512
    sandbox_command_timeout_seconds: int = 600
    sandbox_setup_timeout_seconds: int = 900
    sandbox_allow_network_for_install: bool = False
    sandbox_python_image: str = "python:3.11-slim"
    sandbox_node_image: str = "node:20-slim"
    sandbox_output_limit_chars: int = 20_000

    # --- Observability (LangSmith) -----------------------------------------
    # The standard LANGSMITH_* / LANGCHAIN_TRACING_V2 variable names are honoured. DevFlow reads them
    # itself and routes every trace through one redacting client (see app/observability).
    langsmith_tracing: bool = Field(
        default=False, validation_alias=AliasChoices("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")
    )
    langsmith_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")
    )
    langsmith_project: str = Field(
        default="devflow-ai", validation_alias=AliasChoices("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT")
    )
    langsmith_endpoint: str = Field(
        default="https://api.smith.langchain.com",
        validation_alias=AliasChoices("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT"),
    )
    langsmith_hide_content: bool = False  # send only structure/metadata, never prompts, code or outputs
    langsmith_max_field_chars: int = 20_000

    # --- MCP (Model Context Protocol) ----------------------------------------
    mcp_enabled: bool = True  # server-wide switch; users still opt in under Settings
    mcp_servers_file: str | None = None  # JSON file with admin-approved MCP servers
    mcp_builtin_repo_server: bool = True  # read-only repository search/read tools for agents
    mcp_max_tool_calls: int = 6  # per agent invocation
    mcp_max_calls_per_workflow: int = 80
    mcp_connect_timeout_seconds: float = 30.0
    mcp_tool_timeout_seconds: float = 60.0
    mcp_result_max_chars: int = 8_000

    # --- Workflow --------------------------------------------------------
    workflow_max_retries: int = 3
    agent_timeout_seconds: int = 900
    workflow_worker_threads: int = 4
    require_execution_approval: bool = True
    require_release_approval: bool = True
    resume_workflows_on_startup: bool = True

    @field_validator("cors_origins", "protected_branch_patterns", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def checkpoint_postgres_dsn(self) -> str:
        """psycopg-compatible DSN (without the SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    def resolved_checkpoint_backend(self) -> str:
        if self.checkpoint_backend != "auto":
            return self.checkpoint_backend
        if self.database_url.startswith("postgresql"):
            return "postgres"
        return "sqlite"


@lru_cache
def get_settings() -> Settings:
    return Settings()
