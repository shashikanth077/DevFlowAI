"""Task Orchestrator planning schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel, ListOf, LLMModel, LowerStr, StrList, Text

AgentRole = Literal["frontend", "backend"]
TaskStatus = Literal["pending", "in_progress", "completed", "needs_fix", "failed", "blocked", "cancelled"]


class PlannedTask(LLMModel):
    id: Text
    title: Text
    description: Text = ""
    assigned_agent: Annotated[AgentRole, LowerStr]
    dependencies: StrList = Field(default_factory=list)
    target_files: StrList = Field(default_factory=list)
    acceptance_criteria: StrList = Field(default_factory=list)


class TaskPlan(LLMModel):
    tasks: Annotated[list[PlannedTask], ListOf] = Field(default_factory=list)


class TaskState(BaseModel):
    """Task representation stored in the LangGraph state."""

    id: str
    title: str
    description: str = ""
    assigned_agent: AgentRole
    dependencies: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: TaskStatus = "pending"
    attempts: int = 0
    notes: str = ""
    position: int = 0


class TaskOut(APIModel):
    id: str
    task_key: str
    position: int
    title: str
    description: str
    assigned_agent: str
    status: str
    dependencies: list[str]
    target_files: list[str]
    acceptance_criteria: list[str]
    attempts: int
    notes: str
