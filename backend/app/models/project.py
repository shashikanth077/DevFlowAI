from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base, TimestampMixin
from app.models.base import new_id

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workflow import WorkflowExecution


class GitHubRepository(TimestampMixin, Base):
    __tablename__ = "github_repositories"
    __table_args__ = (UniqueConstraint("user_id", "full_name", name="uq_github_repositories_user_full_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(400), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(200), default="main", nullable=False)
    private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    html_url: Mapped[str] = mapped_column(String(500), nullable=False)
    clone_url: Mapped[str] = mapped_column(String(500), nullable=False)

    projects: Mapped[list[Project]] = relationship(back_populates="repository")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("github_repositories.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_branch: Mapped[str] = mapped_column(String(200), nullable=False)

    owner: Mapped[User] = relationship(back_populates="projects")
    repository: Mapped[GitHubRepository] = relationship(back_populates="projects")
    workflows: Mapped[list[WorkflowExecution]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="WorkflowExecution.created_at.desc()"
    )
