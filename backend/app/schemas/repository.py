"""Repository Analysis Agent schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ListOf, LLMModel, LowerStr, StrList, Text

ComponentKind = Literal["frontend", "backend", "library", "unknown"]


class ProjectComponent(BaseModel):
    """A buildable unit inside the repository (e.g. ``frontend/`` or the repo root)."""

    path: str = "."
    kind: ComponentKind = "unknown"
    language: str = "unknown"
    frameworks: list[str] = Field(default_factory=list)
    package_manager: str | None = None
    install_commands: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    lint_commands: list[str] = Field(default_factory=list)
    build_commands: list[str] = Field(default_factory=list)
    sandbox_image: str = ""
    has_tests: bool = False


class RelevantFile(LLMModel):
    path: Text
    reason: Text = ""
    action: Annotated[Literal["modify", "create", "reference"], LowerStr] = "reference"


class RepositoryInsights(LLMModel):
    """The LLM-produced part of repository analysis."""

    architecture_summary: Text
    conventions: StrList = Field(default_factory=list)
    relevant_files: Annotated[list[RelevantFile], ListOf] = Field(default_factory=list)


class RepositoryAnalysis(BaseModel):
    total_files: int = 0
    file_tree: str = ""
    languages: dict[str, int] = Field(default_factory=dict)
    frameworks: list[str] = Field(default_factory=list)
    components: list[ProjectComponent] = Field(default_factory=list)
    dependency_files: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    architecture_summary: str = ""
    conventions: list[str] = Field(default_factory=list)
    relevant_files: list[RelevantFile] = Field(default_factory=list)
    head_commit: str = ""
