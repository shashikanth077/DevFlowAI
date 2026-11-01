"""Shared implementation for the Frontend and Backend Development Agents.

The LLM returns complete file contents (a :class:`CodeChangeSet`). Before any
change touches disk it passes a set of guards so that agents never blindly
overwrite project files:

* the path must be inside the workspace, outside ``.git``/vendor directories
  and must not be a credential file;
* a file changed by the *other* development agent in this workflow is off
  limits (prevents parallel agents from clobbering each other);
* an existing file may only be modified if the agent was shown its current
  content in the prompt;
* rewrites that drop most of an existing file, or that contain "rest of the
  code unchanged" placeholders, are rejected as truncated output.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.base import BaseAgent, format_files, to_json
from app.core.errors import DevFlowError, UnsafePathError
from app.schemas.code import CodeChangeSet, FileEdit

_PLACEHOLDER_RE = re.compile(
    r"(\.\.\.\s*(rest|remaining) of (the )?(code|file)|existing code (here|unchanged|remains)|"
    r"\(unchanged\)|<\s*existing code\s*>|// \.\.\. ?$|# \.\.\. ?$)",
    re.IGNORECASE | re.MULTILINE,
)


class ChangeRejected(Exception):
    pass


class DevelopmentAgent(BaseAgent):
    role: str = "backend"
    role_prompt: str = ""

    @property
    def system_prompt(self) -> str:
        return (
            f"{self.role_prompt}\n\n"
            "You are working inside an EXISTING repository. Follow its conventions exactly.\n"
            "Output rules:\n"
            "- Return every file you create or change in `changes` with its COMPLETE final content.\n"
            "- Never abbreviate content with placeholders such as '... rest of code' - output whole files.\n"
            "- action is 'modify' for files shown to you and 'create' for new files.\n"
            "- Only change files needed for the task; do not reformat unrelated code.\n"
            "- Never write secrets, tokens or credentials; read configuration from environment variables.\n"
            "- Add or update automated tests for the behaviour you implement."
        )

    # -- entry point ------------------------------------------------------------------

    def run(self, state: dict) -> dict[str, Any]:
        tasks = [t for t in state.get("development_tasks", []) if t["assigned_agent"] == self.role]
        feedback = (state.get("fix_feedback") or {}).get(self.role) or []
        ws = self.rt.workspace()
        ownership: dict[str, str] = dict(state.get("file_ownership", {}))
        touched: list[dict[str, str]] = []
        task_updates: list[dict] = []
        summaries: list[str] = []

        if feedback:
            self.log(f"Correction round {state.get('retry_count', 0)}: addressing {len(feedback)} findings")
            targets = [p for p, owner in ownership.items() if owner == self.role]
            targets += self._paths_mentioned(feedback, ws)
            for task in tasks:
                targets += task["target_files"]
            result, context = self._generate(state, ws, targets, self._fix_prompt(state, feedback, tasks))
            changed = self._apply(ws, result, ownership, allowed_existing=context)
            touched += changed
            summaries.append(result.summary)
            for task in tasks:
                if task["status"] in ("needs_fix", "completed", "failed"):
                    task_updates.append({**task, "status": "completed" if changed else "failed",
                                         "attempts": task.get("attempts", 0) + 1,
                                         "notes": f"Fix round: {result.summary}"[:2000]})
            if not changed:
                raise DevFlowError(f"{self.name} produced no applicable fixes for the reported failures")
        else:
            for task in sorted(tasks, key=lambda t: t.get("position", 0)):
                if task["status"] == "completed":
                    continue
                self.rt.check_cancelled()
                self.log(f"Implementing {task['id']}: {task['title']}")
                self.rt.recorder.save_tasks([{**task, "status": "in_progress"}])
                try:
                    result, context = self._generate(state, ws, task["target_files"], self._task_prompt(state, task))
                    changed = self._apply(ws, result, ownership, allowed_existing=context)
                except DevFlowError as exc:
                    task_updates.append({**task, "status": "failed", "attempts": task.get("attempts", 0) + 1,
                                         "notes": exc.message[:2000]})
                    self.rt.recorder.save_tasks([task_updates[-1]])
                    raise
                status = "completed" if changed else "failed"
                task_updates.append({**task, "status": status, "attempts": task.get("attempts", 0) + 1,
                                     "notes": result.summary[:2000]})
                self.rt.recorder.save_tasks([task_updates[-1]])
                touched += changed
                summaries.append(f"{task['id']}: {result.summary}")
            if tasks and not touched:
                raise DevFlowError(f"{self.name} did not produce any file changes for its tasks")

        created = [c["path"] for c in touched if c["change_type"] == "created"]
        modified = [c["path"] for c in touched if c["change_type"] == "modified"]
        self.log(f"Changed {len(touched)} files ({len(created)} created, {len(modified)} modified)")
        return {
            "development_tasks": task_updates,
            "generated_files": created,
            "modified_files": modified,
            "file_ownership": {c["path"]: self.role for c in touched},
            "agent_summaries": {self.role: "\n".join(summaries)[:4000]},
        }

    # -- prompting ------------------------------------------------------------------

    def _context(self, state: dict, ws, target_files: list[str]) -> tuple[str, list[str]]:
        repo = state.get("repository_analysis", {})
        reference = [f["path"] for f in repo.get("relevant_files", []) if f.get("action") in ("reference", "modify")]
        changed_in_workflow = list(state.get("file_ownership", {}))
        paths = [p for p in target_files if ws.exists(p)] + changed_in_workflow + reference
        return format_files(ws, paths, budget=self.llm.config.context_chars // 2, per_file=20_000)

    def _task_prompt(self, state: dict, task: dict) -> str:
        plan = state.get("architecture_plan", {})
        return (
            f"TASK {task['id']}: {task['title']}\n{task['description']}\n"
            f"Target files: {task['target_files']}\n"
            f"Task acceptance criteria: {to_json(task.get('acceptance_criteria', []), 3_000)}\n\n"
            f"Overall acceptance criteria: {to_json(state.get('acceptance_criteria', []), 4_000)}\n"
            f"Architecture approach: {plan.get('approach', '')}\n"
            f"API endpoints: {to_json(plan.get('api_endpoints', []), 4_000)}\n"
            f"Data models: {to_json(plan.get('data_models', []), 4_000)}\n"
            f"Repository conventions: {to_json(state.get('repository_analysis', {}).get('conventions', []), 2_000)}\n"
        )

    def _fix_prompt(self, state: dict, feedback: list[str], tasks: list[dict]) -> str:
        return (
            "Your previous changes did not pass verification. Fix ALL of the following problems.\n"
            + "\n".join(f"- {item}" for item in feedback)
            + f"\n\nYour tasks: {to_json([{k: t[k] for k in ('id', 'title', 'target_files')} for t in tasks], 4_000)}\n"
            f"Acceptance criteria: {to_json(state.get('acceptance_criteria', []), 4_000)}\n"
        )

    def _generate(self, state: dict, ws, target_files: list[str], task_text: str) -> tuple[CodeChangeSet, set[str]]:
        files_text, included = self._context(state, ws, target_files)
        tree = self.llm.truncate(state.get("repository_analysis", {}).get("file_tree", ""), 8_000)
        user = (
            f"{task_text}\n\nRepository files:\n{tree}\n\n"
            f"Current contents of files you may modify (complete files):\n{files_text or '(none)'}"
        )
        findings = self.tool_context(task_text)
        if findings:
            user += f"\n\n{findings}"
        result = self.llm.structured(self.name, self.system_prompt, user, CodeChangeSet)
        return result, set(included)

    # -- applying changes ---------------------------------------------------------------

    def _apply(self, ws, result: CodeChangeSet, ownership: dict[str, str], *, allowed_existing: set[str]) -> list[dict[str, str]]:
        applied: list[dict[str, str]] = []
        for edit in result.changes:
            try:
                applied.append(self._apply_one(ws, edit, ownership, allowed_existing))
            except (ChangeRejected, UnsafePathError) as exc:
                self.log(f"Rejected change to {edit.path}: {exc}", level="warning")
        return applied

    def _apply_one(self, ws, edit: FileEdit, ownership: dict[str, str], allowed_existing: set[str]) -> dict[str, str]:
        path = ws.normalize(edit.path)
        ws.resolve(path, for_write=True)
        owner = ownership.get(path)
        if owner and owner != self.role:
            raise ChangeRejected(f"file is owned by the {owner} agent in this workflow")
        if _PLACEHOLDER_RE.search(edit.content):
            raise ChangeRejected("content contains placeholder text instead of complete code")
        if not edit.content.strip():
            raise ChangeRejected("empty file content")
        with self.rt.write_lock:
            original = ws.read_file(path)
            exists = ws.exists(path)
            if exists and path not in allowed_existing and owner != self.role:
                raise ChangeRejected("refusing to overwrite an existing file whose content was not reviewed")
            if exists and original is not None:
                old_lines = len(original.splitlines())
                new_lines = len(edit.content.splitlines())
                if old_lines >= 40 and new_lines < old_lines * 0.3:
                    raise ChangeRejected(
                        f"rewrite shrinks file from {old_lines} to {new_lines} lines (likely truncated output)"
                    )
                if original.rstrip("\n") == edit.content.rstrip("\n"):
                    raise ChangeRejected("no changes")
            ws.write_file(path, edit.content)
            ownership[path] = self.role
        change_type = "modified" if ws.exists_in_head(path) else "created"
        self.log(f"{'Created' if change_type == 'created' else 'Updated'} {path}", reason=edit.reason[:300])
        return {"path": path, "change_type": change_type}

    @staticmethod
    def _paths_mentioned(feedback: list[str], ws) -> list[str]:
        found: list[str] = []
        for item in feedback:
            for match in re.findall(r"[\w./-]+\.[A-Za-z0-9]{1,5}", item):
                candidate = match.removeprefix("./")
                if ws.exists(candidate):
                    found.append(candidate)
        return found

