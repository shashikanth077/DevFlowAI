"""Software Architecture Agent output schema."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import ListOf, LLMModel, LowerStr, StrList, Text


class APIEndpoint(LLMModel):
    method: Text = "GET"
    path: Text
    description: Text = ""
    request_body: Text = ""
    response_body: Text = ""


class DataModel(LLMModel):
    name: Text
    fields: StrList = Field(default_factory=list)
    validation_rules: StrList = Field(default_factory=list)


class FileChangePlan(LLMModel):
    path: Text
    action: Annotated[Literal["create", "modify"], LowerStr] = "modify"
    area: Annotated[Literal["frontend", "backend"], LowerStr] = "backend"
    description: Text = ""


class ArchitecturePlan(LLMModel):
    approach: Text
    frontend_changes: StrList = Field(default_factory=list)
    backend_changes: StrList = Field(default_factory=list)
    api_endpoints: Annotated[list[APIEndpoint], ListOf] = Field(default_factory=list)
    data_models: Annotated[list[DataModel], ListOf] = Field(default_factory=list)
    file_plan: Annotated[list[FileChangePlan], ListOf] = Field(default_factory=list)
    testing_strategy: StrList = Field(default_factory=list)
    risks: StrList = Field(default_factory=list)
