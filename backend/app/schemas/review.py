"""Code Review & Security Agent schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ListOf, LLMModel, LowerStr, Text

Severity = Literal["critical", "high", "medium", "low", "info"]
BLOCKING_SEVERITIES = {"critical", "high"}


class ReviewIssue(LLMModel):
    severity: Annotated[Severity, LowerStr] = "medium"
    category: Annotated[
        Literal[
            "bug", "security", "secret", "validation", "error_handling", "style",
            "unnecessary_change", "testing", "performance", "other",
        ],
        LowerStr,
    ] = "other"
    file: Text = ""
    line: int | None = None
    message: Text
    suggestion: Text = ""
    responsible_agent: Annotated[Literal["frontend", "backend", "unknown"], LowerStr] = "unknown"


class LLMReview(LLMModel):
    approved: bool
    summary: Text
    issues: Annotated[list[ReviewIssue], ListOf] = Field(default_factory=list)


class ReviewReport(BaseModel):
    approved: bool
    summary: str
    issues: list[ReviewIssue] = Field(default_factory=list)
    automated_findings: list[ReviewIssue] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    responsible_agents: list[str] = Field(default_factory=list)
    diff_hash: str
    reviewer_model: str = ""
