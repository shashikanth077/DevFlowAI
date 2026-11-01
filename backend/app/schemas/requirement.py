"""Requirement Analyst Agent output schema."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ListOf, LLMModel, LowerStr, StrList, Text


class FunctionalRequirement(LLMModel):
    id: Text = Field(description="Identifier such as FR-1")
    description: Text
    priority: Annotated[Literal["must", "should", "could"], LowerStr] = "must"


class ProposedTask(LLMModel):
    title: Text
    description: Text = ""
    area: Annotated[Literal["frontend", "backend", "fullstack", "other"], LowerStr] = "other"


class RequirementAnalysis(LLMModel):
    title: Text = Field(description="Short feature title (max ~8 words)")
    summary: Text
    business_objectives: StrList = Field(default_factory=list)
    functional_requirements: Annotated[list[FunctionalRequirement], ListOf] = Field(default_factory=list)
    non_functional_requirements: StrList = Field(default_factory=list)
    ambiguities: StrList = Field(default_factory=list, description="Missing or ambiguous information")
    assumptions: StrList = Field(default_factory=list)
    acceptance_criteria: StrList = Field(default_factory=list)
    proposed_tasks: Annotated[list[ProposedTask], ListOf] = Field(default_factory=list)


class RequirementAnalysisRequest(LLMModel):
    requirement: str = Field(min_length=10, max_length=20_000)
