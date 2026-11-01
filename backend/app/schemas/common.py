"""Lenient field types for LLM-produced structured output.

Local models occasionally return a string where a list is expected, ``null``
for empty lists or capitalised enum values. These helpers normalise such
output *before* strict Pydantic validation so that malformed responses still
fail loudly, while harmless formatting differences do not.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict


def _to_str_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        lines = [line.strip(" -*\t") for line in stripped.splitlines()]
        return [line for line in lines if line]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                text = item.get("description") or item.get("text") or item.get("name") or item.get("title")
                out.append(str(text) if text else json.dumps(item))
            elif item is not None:
                out.append(str(item))
        return out
    return value


def _to_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    return value


def _lower(value: Any) -> Any:
    return value.strip().lower().replace(" ", "_").replace("-", "_") if isinstance(value, str) else value


def _to_str(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return value


StrList = Annotated[list[str], BeforeValidator(_to_str_list)]
Text = Annotated[str, BeforeValidator(_to_str)]
LowerStr = BeforeValidator(_lower)
ListOf = BeforeValidator(_to_list)


class LLMModel(BaseModel):
    """Base for schemas produced by an LLM: unknown keys are ignored."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
