"""Agent 7 - QA & Testing.

Runs the repository's own test, lint and build commands for every component
touched by the change, inside the Docker sandbox. A run is only reported as
``passed`` when at least one test command actually executed and every command
exited with status 0. Missing tests are reported as ``not_run``, never as a
success.
"""

from __future__ import annotations

import time
from pathlib import PurePosixPath

from app.agents.base import BaseAgent, infer_area, to_json
from app.core.errors import LLMError, SandboxError
from app.schemas.testing import CommandReport, FailureAnalysis, TestFailure, TestReport

SYSTEM_PROMPT = """You are a QA engineer analysing failed automated checks.
For each distinct failure, summarise the root cause in one or two sentences, name the files that most
likely need to change, state which developer is responsible ("frontend" or "backend") and give a
concrete suggested fix. Base your analysis strictly on the command output provided."""


def _in_component(path: str, component_path: str) -> bool:
    if component_path in (".", ""):
        return True
    return PurePosixPath(path).parts[: len(PurePosixPath(component_path).parts)] == PurePosixPath(component_path).parts


class TestingAgent(BaseAgent):
    __test__ = False
    name = "qa_engineer"

    def plan_commands(self, state: dict) -> list[dict]:
        """Components (and their commands) that will be executed - shown at the approval gate."""
        components = state.get("repository_analysis", {}).get("components", [])
        changed = list(state.get("generated_files", [])) + list(state.get("modified_files", []))
        selected: list[dict] = []
        for path in changed:
            owners = [c for c in components if _in_component(path, c.get("path", "."))]
            if not owners:
                continue
            best = max(owners, key=lambda c: len(PurePosixPath(c.get("path", ".")).parts) if c.get("path") not in (".", "") else 0)
            if best not in selected:
                selected.append(best)
        return [
            {
                "component": comp["path"],
                "kind": comp.get("kind"),
                "image": comp.get("sandbox_image"),
                "setup": comp.get("install_commands", []),
                "test": comp.get("test_commands", []),
                "lint": comp.get("lint_commands", []),
                "build": comp.get("build_commands", []),
            }
            for comp in selected
        ]

    def run(self, state: dict) -> TestReport:
        started = time.monotonic()
        plans = self.plan_commands(state)
        commands: list[CommandReport] = []
        notes: list[str] = []
        changed = list(state.get("generated_files", [])) + list(state.get("modified_files", []))
        ws = self.rt.workspace()

        test_commands_run = 0
        for plan in plans:
            self.rt.check_cancelled()
            if not plan["test"]:
                notes.append(f"Component '{plan['component']}' has no automated test command.")
            to_run = [("test", c) for c in plan["test"]] + [("lint", c) for c in plan["lint"]] + [
                ("build", c) for c in plan["build"]
            ]
            if not to_run:
                continue
            if not plan["image"]:
                notes.append(f"No sandbox image known for component '{plan['component']}'; skipped.")
                continue
            self.log(f"Running {len(to_run)} commands for '{plan['component']}' in sandbox ({plan['image']})")
            run = self.rt.sandbox.run(
                ws.root, image=plan["image"], workdir=plan["component"],
                setup_commands=plan["setup"], commands=[c for _, c in to_run],
            )
            for setup in run.setup:
                commands.append(CommandReport(
                    component=plan["component"], phase="setup", command=setup.command, exit_code=setup.exit_code,
                    stdout=setup.stdout, stderr=setup.stderr, duration_ms=setup.duration_ms, timed_out=setup.timed_out,
                ))
            for (phase, _), result in zip(to_run, run.commands, strict=False):
                commands.append(CommandReport(
                    component=plan["component"], phase=phase, command=result.command, exit_code=result.exit_code,
                    stdout=result.stdout, stderr=result.stderr, duration_ms=result.duration_ms,
                    timed_out=result.timed_out,
                ))
                if phase == "test":
                    test_commands_run += 1
                self.log(f"[{phase}] {result.command} -> exit {result.exit_code}",
                         level="info" if result.succeeded else "warning")

        notes += self._coverage_notes(changed, plans)
        failed = [c for c in commands if not c.succeeded]
        duration = int((time.monotonic() - started) * 1000)
        if failed:
            failures = self._analyse(state, failed)
            responsible = sorted({f.responsible_agent for f in failures if f.responsible_agent != "unknown"})
            report = TestReport(
                status="failed", summary=f"{len(failed)} of {len(commands)} commands failed",
                commands=commands, failures=failures, coverage_notes=notes,
                responsible_agents=responsible, duration_ms=duration,
            )
        elif test_commands_run == 0:
            report = TestReport(
                status="not_run",
                summary="No automated tests were executed for the changed components. "
                "The change is NOT verified by tests.",
                commands=commands, coverage_notes=notes, duration_ms=duration,
            )
        else:
            report = TestReport(
                status="passed", summary=f"All {len(commands)} commands passed ({test_commands_run} test commands)",
                commands=commands, coverage_notes=notes, duration_ms=duration,
            )
        self.log(report.summary, level="info" if report.status == "passed" else "warning")
        return report

    def _coverage_notes(self, changed: list[str], plans: list[dict]) -> list[str]:
        from app.services.repository_service import TEST_FILE_RE

        source = [p for p in changed if not TEST_FILE_RE.search(p) and PurePosixPath(p).suffix in
                  {".py", ".ts", ".tsx", ".js", ".jsx", ".go"}]
        tests = [p for p in changed if TEST_FILE_RE.search(p)]
        notes = []
        if source and not tests:
            notes.append("Source files changed but no test files were added or updated: " + ", ".join(source[:10]))
        return notes

    def _analyse(self, state: dict, failed: list[CommandReport]) -> list[TestFailure]:
        ownership: dict[str, str] = state.get("file_ownership", {})
        components = state.get("repository_analysis", {}).get("components", [])
        output = "\n\n".join(
            f"$ {c.command}  (component {c.component}, phase {c.phase}, exit {c.exit_code})\n"
            f"STDOUT:\n{c.stdout[-6000:]}\nSTDERR:\n{c.stderr[-6000:]}"
            for c in failed
        )
        user = (
            f"Files changed in this workflow and the responsible developer:\n{to_json(ownership, 4_000)}\n\n"
            f"Failed commands:\n{output}"
        )
        try:
            failures = self.llm.structured(self.name, SYSTEM_PROMPT, user, FailureAnalysis).failures
        except LLMError as exc:
            self.log(f"Failure analysis by LLM unavailable ({exc.message}); using heuristics", level="warning")
            failures = []
        if not failures:
            failures = [TestFailure(command=c.command, summary=(c.stderr or c.stdout)[-1500:] or "Command failed",
                                    responsible_agent="unknown") for c in failed]
        for failure in failures:
            command = next((c for c in failed if c.command == failure.command), failed[0])
            failure.command = command.command
            if failure.responsible_agent == "unknown":
                owners = {ownership.get(f) for f in failure.files} - {None}
                if len(owners) == 1:
                    failure.responsible_agent = owners.pop()  # type: ignore[assignment]
                else:
                    comp = next((c for c in components if c["path"] == command.component), None)
                    kind = comp.get("kind") if comp else None
                    if kind not in ("frontend", "backend"):
                        roles = set(ownership.values())
                        kind = roles.pop() if len(roles) == 1 else infer_area(command.component + "/x", components)
                    failure.responsible_agent = kind if kind in ("frontend", "backend") else "unknown"  # type: ignore[assignment]
        return failures


def feedback_from_report(report: TestReport, ownership: dict[str, str]) -> dict[str, list[str]]:
    """Group actionable test feedback per responsible development agent."""
    feedback: dict[str, list[str]] = {}
    roles = set(ownership.values()) or {"backend"}
    for failure in report.failures:
        targets = [failure.responsible_agent] if failure.responsible_agent in ("frontend", "backend") else sorted(roles)
        command = next((c for c in report.commands if c.command == failure.command), None)
        output = ""
        if command:
            output = f"\nOutput:\n{(command.stdout[-2500:] + command.stderr[-2500:]).strip()}"
        text = (f"Command `{failure.command}` failed: {failure.summary}. Files: {', '.join(failure.files) or 'n/a'}. "
                f"Suggested fix: {failure.suggested_fix or 'n/a'}{output}")
        for role in targets:
            feedback.setdefault(role, []).append(text)
    return feedback


__all__ = ["SandboxError", "TestingAgent", "feedback_from_report"]
