"""QA / Testing Agent schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ListOf, LLMModel, LowerStr, StrList, Text

TestStatus = Literal["passed", "failed", "not_run", "error"]


class CommandReport(BaseModel):
    component: str
    phase: Literal["setup", "test", "lint", "build"]
    command: str
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class TestFailure(LLMModel):
    command: Text = ""
    summary: Text
    responsible_agent: Annotated[Literal["frontend", "backend", "unknown"], LowerStr] = "unknown"
    files: StrList = Field(default_factory=list)
    suggested_fix: Text = ""


class FailureAnalysis(LLMModel):
    failures: Annotated[list[TestFailure], ListOf] = Field(default_factory=list)


class TestReport(BaseModel):
    __test__ = False

    status: TestStatus
    summary: str
    commands: list[CommandReport] = Field(default_factory=list)
    failures: list[TestFailure] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)
    responsible_agents: list[str] = Field(default_factory=list)
    duration_ms: int = 0
