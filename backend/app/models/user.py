from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base, TimestampMixin, utcnow
from app.models.base import JSONType, new_id

if TYPE_CHECKING:
    from app.models.project import Project


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    projects: Mapped[list[Project]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    settings: Mapped[UserSettings | None] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    github_connection: Mapped[GitHubConnection | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class UserSettings(TimestampMixin, Base):
    """Per-user LLM and workflow configuration (Settings screen)."""

    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(200), nullable=False)
    llm_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    llm_base_url: Mapped[str | None] = mapped_column(String(500))
    llm_api_key_encrypted: Mapped[str | None] = mapped_column(String(2000))
    agent_models: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    workflow_max_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    require_execution_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    require_release_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sandbox_allow_network_for_install: Mapped[bool] = mapped_column(Boolean, nullable=False)
    create_draft_pull_requests: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="settings")


class GitHubConnection(TimestampMixin, Base):
    """Encrypted GitHub credential. The token is never returned by the API or sent to an LLM."""

    __tablename__ = "github_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    login: Mapped[str] = mapped_column(String(200), nullable=False)
    token_encrypted: Mapped[str] = mapped_column(String(4000), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="github_connection")
