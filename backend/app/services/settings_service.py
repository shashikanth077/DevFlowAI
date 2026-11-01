"""User settings and credential resolution."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import GitHubNotConnectedError
from app.core.security import decrypt_secret, encrypt_secret
from app.models.user import GitHubConnection, UserSettings
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.services.llm_service import LLMConfig


def get_or_create_settings(db: Session, user_id: str) -> UserSettings:
    row = db.query(UserSettings).filter_by(user_id=user_id).one_or_none()
    if row is None:
        s = get_settings()
        row = UserSettings(
            user_id=user_id,
            llm_provider=s.llm_provider,
            llm_model=s.llm_model,
            llm_temperature=s.llm_temperature,
            llm_base_url=None,
            agent_models={},
            workflow_max_retries=s.workflow_max_retries,
            require_execution_approval=s.require_execution_approval,
            require_release_approval=s.require_release_approval,
            sandbox_allow_network_for_install=s.sandbox_allow_network_for_install,
            create_draft_pull_requests=False,
            mcp_enabled=False,
            mcp_disabled_servers=[],
        )
        db.add(row)
        db.flush()
    return row


def to_out(row: UserSettings) -> SettingsOut:
    return SettingsOut(
        llm_provider=row.llm_provider,  # type: ignore[arg-type]
        llm_model=row.llm_model,
        llm_temperature=row.llm_temperature,
        llm_base_url=row.llm_base_url,
        llm_api_key_configured=bool(row.llm_api_key_encrypted),
        agent_models=row.agent_models or {},
        workflow_max_retries=row.workflow_max_retries,
        require_execution_approval=row.require_execution_approval,
        require_release_approval=row.require_release_approval,
        sandbox_allow_network_for_install=row.sandbox_allow_network_for_install,
        create_draft_pull_requests=row.create_draft_pull_requests,
        mcp_enabled=row.mcp_enabled,
        mcp_disabled_servers=list(row.mcp_disabled_servers or []),
    )


def apply_update(row: UserSettings, update: SettingsUpdate) -> None:
    data = update.model_dump(exclude_unset=True)
    api_key = data.pop("llm_api_key", None)
    if api_key is not None:
        row.llm_api_key_encrypted = encrypt_secret(api_key) if api_key else None
    if "llm_base_url" in data:
        row.llm_base_url = data.pop("llm_base_url") or None
    if "mcp_disabled_servers" in data:
        row.mcp_disabled_servers = sorted(set(data.pop("mcp_disabled_servers") or []))
    if "agent_models" in data:
        row.agent_models = {k: v for k, v in (data.pop("agent_models") or {}).items() if v}
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)


def llm_config_for(row: UserSettings) -> LLMConfig:
    return LLMConfig.from_settings(
        provider=row.llm_provider,
        model=row.llm_model,
        temperature=row.llm_temperature,
        base_url=row.llm_base_url,
        api_key=decrypt_secret(row.llm_api_key_encrypted) if row.llm_api_key_encrypted else None,
        agent_models=dict(row.agent_models or {}),
    )


def github_token_for(db: Session, user_id: str) -> str | None:
    conn = db.query(GitHubConnection).filter_by(user_id=user_id).one_or_none()
    if conn is not None:
        return decrypt_secret(conn.token_encrypted)
    return get_settings().github_token


def require_github_token(db: Session, user_id: str) -> str:
    token = github_token_for(db, user_id)
    if not token:
        raise GitHubNotConnectedError("GitHub is not connected. Add a personal access token in Settings.")
    return token
