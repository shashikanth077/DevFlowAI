"""Shared agent helpers."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from app.orchestration.runtime import WorkflowRuntime
from app.services.repository_service import Workspace


class BaseAgent:
    """Common plumbing: access to the runtime, LLM and workflow log."""

    name: str = "agent"

    def __init__(self, runtime: WorkflowRuntime) -> None:
        self.rt = runtime
        self.llm = runtime.llm

    def log(self, message: str, *, level: str = "info", **data: Any) -> None:
        self.rt.recorder.log(message, level=level, agent=self.name, data=data or None)


def to_json(data: Any, limit: int = 20_000) -> str:
    text = json.dumps(data, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]"


def format_files(ws: Workspace, paths: list[str], *, budget: int = 40_000, per_file: int = 15_000) -> tuple[str, list[str]]:
    """Render file contents for a prompt. Returns the text and the paths actually included."""
    chunks: list[str] = []
    included: list[str] = []
    used = 0
    for path in dict.fromkeys(paths):
        content = ws.read_file(path)
        if content is None:
            continue
        if len(content) > per_file:
            continue  # partial files must never be presented as complete; skip instead
        block = f"===== FILE: {path} =====\n{content}\n===== END FILE: {path} =====\n"
        if used + len(block) > budget:
            break
        chunks.append(block)
        included.append(path)
        used += len(block)
    return "\n".join(chunks), included


def infer_area(path: str, components: list[dict[str, Any]]) -> str | None:
    """Return 'frontend'/'backend' based on the component that contains ``path``."""
    best: tuple[int, str] | None = None
    parts = PurePosixPath(path).parts
    for comp in components:
        comp_path = comp.get("path", ".")
        comp_parts = () if comp_path in (".", "") else PurePosixPath(comp_path).parts
        if parts[: len(comp_parts)] == comp_parts and comp.get("kind") in ("frontend", "backend"):
            if best is None or len(comp_parts) > best[0]:
                best = (len(comp_parts), comp["kind"])
    if best:
        return best[1]
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in {".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss", ".html"}:
        return "frontend"
    if suffix in {".py", ".go", ".java", ".rb", ".sql"}:
        return "backend"
    return None
