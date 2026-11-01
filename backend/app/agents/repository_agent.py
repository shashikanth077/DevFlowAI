"""Agent 2 - Repository Analyst."""

from __future__ import annotations

from app.agents.base import BaseAgent, format_files, to_json
from app.core.errors import UnsafePathError
from app.schemas.repository import RelevantFile, RepositoryAnalysis, RepositoryInsights

SYSTEM_PROMPT = """You are a staff engineer onboarding onto an existing codebase.
Given the repository structure, key configuration files and a feature specification:
- Summarise the existing architecture (layers, frameworks, how code is organised).
- List the coding conventions you observe (naming, folder layout, state management, testing style).
- Select the files that are relevant to the feature: files to MODIFY, new files to CREATE (follow the
  existing folder conventions) and files to keep as REFERENCE for patterns.
Only reference files that appear in the provided file list for 'modify' and 'reference'.
Never propose changes to lock files, build output, vendored dependencies or secrets."""

_KEY_FILE_NAMES = ("README.md", "readme.md", "package.json", "pyproject.toml", "requirements.txt", "tsconfig.json")


class RepositoryAnalystAgent(BaseAgent):
    name = "repository_analyst"

    def run(self, *, clone_url: str, base_branch: str, requirement_analysis: dict) -> tuple[RepositoryAnalysis, str]:
        self.log(f"Cloning repository (branch {base_branch}) into isolated workspace")
        ws = self.rt.repositories.clone(clone_url, base_branch, self.rt.workflow_id, token=self.rt.token_provider())
        analysis = self.rt.repositories.analyze(ws)
        self.log(
            f"Scanned {analysis.total_files} files; languages: {', '.join(analysis.languages) or 'none'}; "
            f"components: {', '.join(f'{c.path} ({c.kind})' for c in analysis.components) or 'none'}"
        )
        key_files = [f for f in analysis.config_files if f.rsplit("/", 1)[-1] in _KEY_FILE_NAMES]
        key_files += [f for f in ("README.md", "readme.md") if ws.exists(f)]
        files_text, _ = format_files(ws, key_files, budget=20_000, per_file=8_000)
        user = (
            f"Feature specification:\n{to_json(requirement_analysis, 8_000)}\n\n"
            f"Detected components:\n{to_json([c.model_dump() for c in analysis.components], 4_000)}\n\n"
            f"Repository files:\n{self.llm.truncate(analysis.file_tree, 20_000)}\n\n"
            f"Key files:\n{files_text}"
        )
        insights = self.llm.structured(self.name, SYSTEM_PROMPT, user, RepositoryInsights)
        analysis.architecture_summary = insights.architecture_summary
        analysis.conventions = insights.conventions
        analysis.relevant_files = self._validate_files(ws, insights.relevant_files)
        self.log(f"Selected {len(analysis.relevant_files)} relevant files")
        return analysis, str(ws.root)

    def _validate_files(self, ws, files: list[RelevantFile]) -> list[RelevantFile]:
        seen: set[str] = set()
        valid: list[RelevantFile] = []
        for item in files:
            try:
                path = ws.normalize(item.path)
                ws.resolve(path)
            except UnsafePathError:
                self.log(f"Ignoring unsafe path suggested by model: {item.path}", level="warning")
                continue
            if path in seen:
                continue
            seen.add(path)
            exists = ws.exists(path)
            action = item.action
            if action in ("modify", "reference") and not exists:
                if action == "reference":
                    continue
                action = "create"
            if action == "create" and exists:
                action = "modify"
            valid.append(RelevantFile(path=path, reason=item.reason, action=action))
        return valid
