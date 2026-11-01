from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base, TimestampMixin
from app.models.base import JSONType, new_id

if TYPE_CHECKING:
    from app.models.workflow import WorkflowExecution


class DevelopmentTask(TimestampMixin, Base):
    __tablename__ = "development_tasks"
    __table_args__ = (UniqueConstraint("workflow_id", "task_key", name="uq_development_tasks_workflow_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_key: Mapped[str] = mapped_column(String(40), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    assigned_agent: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    dependencies: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    target_files: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    acceptance_criteria: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    workflow: Mapped[WorkflowExecution] = relationship(back_populates="tasks")
