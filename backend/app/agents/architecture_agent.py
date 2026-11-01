"""Agent 3 - Software Architect."""

from __future__ import annotations

from app.agents.base import BaseAgent, format_files, infer_area, to_json
from app.core.errors import UnsafePathError
from app.schemas.architecture import ArchitecturePlan

SYSTEM_PROMPT = """You are a software architect. Design how to implement the feature inside the
EXISTING repository, reusing its frameworks, patterns and folder structure.
Define: the overall approach, frontend changes, backend changes, REST API endpoints (method, path,
request and response bodies), data models with validation rules, an explicit file plan (every file
to create or modify, with area frontend/backend), the testing strategy and the main risks.
Keep the change set minimal: only touch files that are necessary for the requirement.
Only include frontend work if the repository has a frontend and the requirement needs it; the same
applies to backend work."""


class ArchitectureAgent(BaseAgent):
    name = "architect"

    def run(self, state: dict) -> ArchitecturePlan:
        ws = self.rt.workspace()
        repo = state["repository_analysis"]
        relevant = [f["path"] for f in repo.get("relevant_files", []) if f.get("action") != "create"]
        files_text, _ = format_files(ws, relevant, budget=30_000, per_file=12_000)
        user = (
            f"Feature specification:\n{to_json(state['requirement_analysis'], 10_000)}\n\n"
            f"Architecture summary: {repo.get('architecture_summary', '')}\n"
            f"Conventions: {to_json(repo.get('conventions', []), 3_000)}\n"
            f"Components: {to_json(repo.get('components', []), 4_000)}\n"
            f"Relevant files: {to_json(repo.get('relevant_files', []), 4_000)}\n\n"
            f"Repository files:\n{self.llm.truncate(repo.get('file_tree', ''), 12_000)}\n\n"
            f"Contents of relevant files:\n{files_text}"
        )
        findings = self.tool_context(
            f"Design the implementation of: {state['requirement_analysis'].get('summary', '')}\n"
            f"Relevant files: {[f['path'] for f in repo.get('relevant_files', [])]}"
        )
        if findings:
            user += f"\n\n{findings}"
        self.log("Designing implementation approach")
        plan = self.llm.structured(self.name, SYSTEM_PROMPT, user, ArchitecturePlan)
        components = repo.get("components", [])
        cleaned = []
        for item in plan.file_plan:
            try:
                item.path = ws.normalize(item.path)
                ws.resolve(item.path, for_write=True)
            except UnsafePathError:
                self.log(f"Dropping unsafe planned path {item.path}", level="warning")
                continue
            item.action = "modify" if ws.exists(item.path) else "create"
            item.area = infer_area(item.path, components) or item.area  # type: ignore[assignment]
            cleaned.append(item)
        plan.file_plan = cleaned
        self.log(
            f"Plan: {len(plan.file_plan)} files, {len(plan.api_endpoints)} endpoints, "
            f"{len(plan.data_models)} data models"
        )
        return plan
