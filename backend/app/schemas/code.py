"""Development agent output schemas (file edits)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ListOf, LLMModel, LowerStr, Text


class FileEdit(LLMModel):
    path: Text = Field(description="Repository-relative path using forward slashes")
    action: Annotated[Literal["create", "modify"], LowerStr]
    content: Text = Field(description="The COMPLETE new content of the file")
    reason: Text = ""


class CodeChangeSet(LLMModel):
    summary: Text
    changes: Annotated[list[FileEdit], ListOf] = Field(default_factory=list)
