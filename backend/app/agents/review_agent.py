"""Agent 8 - Code Review & Security.

Independence guarantees:

* The reviewer is read-only: it receives the git diff and never writes files.
* It runs with its own system prompt and can be pinned to a different model
  (``agent_models.code_reviewer``) than the authoring agents.
* Approval is a *policy decision in code*: the LLM verdict is combined with
  deterministic checks (secret scanning, scope, deletions, test status) and
  any critical/high finding blocks approval regardless of the LLM's opinion.
* The approved diff is fingerprinted (SHA-256). The release agent refuses to
  commit if the workspace no longer matches the reviewed diff, and a human
  must still approve the release.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

from app.agents.base import BaseAgent, to_json
from app.core.security import find_secrets
from app.schemas.review import BLOCKING_SEVERITIES, LLMReview, ReviewIssue, ReviewReport

SYSTEM_PROMPT = """You are an independent senior code reviewer and application-security engineer.
You did NOT write this code. Review the diff critically against the requirement and acceptance criteria:
- correctness bugs and unhandled edge cases,
- security vulnerabilities (injection, XSS, broken authz, SSRF, path traversal, unsafe deserialisation),
- hardcoded secrets or credentials,
- missing input validation and error handling on APIs,
- unnecessary or unrelated changes,
- violations of the project's coding standards, and missing tests.
Set approved=true only if the change is correct, secure and complete. Use severity critical/high for
problems that must be fixed before merging. Reference the file (and line when possible) for every issue
and state which developer must fix it ("frontend" or "backend")."""

_DEBUG_RE = re.compile(r"^\+(?!\+\+).*\b(console\.log\(|debugger;|print\(|pdb\.set_trace\(|breakpoint\(\))")


def diff_hash(diff: str) -> str:
    return hashlib.sha256(diff.encode()).hexdigest()


def _added_lines_by_file(diff: str) -> dict[str, list[tuple[int, str]]]:
    files: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    line_no = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            current = path[2:] if path.startswith("b/") else None
            files.setdefault(current or "", [])
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_no = int(match.group(1)) - 1 if match else 0
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            line_no += 1
            files[current].append((line_no, line[1:]))
        elif current is not None and not line.startswith("-"):
            line_no += 1
    return files


class CodeReviewAgent(BaseAgent):
    name = "code_reviewer"

    def automated_checks(self, state: dict, diff: str, numstat: dict[str, tuple[int, int]]) -> list[ReviewIssue]:
        ownership: dict[str, str] = state.get("file_ownership", {})
        issues: list[ReviewIssue] = []
        added = _added_lines_by_file(diff)
        for path, lines in added.items():
            role = ownership.get(path, "unknown")
            for line_no, text in lines:
                for kind, _ in find_secrets(text):
                    issues.append(ReviewIssue(
                        severity="critical", category="secret", file=path, line=line_no,
                        message=f"Possible hardcoded secret ({kind}).",
                        suggestion="Load the value from configuration/environment variables instead.",
                        responsible_agent=role,
                    ))
                is_test = "test" in PurePosixPath(path).name.lower()
                if not is_test and _DEBUG_RE.match("+" + text):
                    issues.append(ReviewIssue(
                        severity="low", category="style", file=path, line=line_no,
                        message="Debug statement left in code.", suggestion="Remove it or use the project logger.",
                        responsible_agent=role,
                    ))
        planned = {f for t in state.get("development_tasks", []) for f in t.get("target_files", [])}
        planned |= {f.get("path") for f in state.get("architecture_plan", {}).get("file_plan", [])}
        for path, (additions, deletions) in numstat.items():
            role = ownership.get(path, "unknown")
            if planned and path not in planned and "test" not in path.lower():
                issues.append(ReviewIssue(
                    severity="info", category="unnecessary_change", file=path,
                    message="File changed outside of the planned file list.",
                    suggestion="Confirm the change is required by the requirement.", responsible_agent=role,
                ))
            if deletions > 150 and deletions > additions * 2:
                issues.append(ReviewIssue(
                    severity="high", category="unnecessary_change", file=path,
                    message=f"Large deletion ({deletions} lines removed, {additions} added).",
                    suggestion="Restore unrelated code; only remove what the task requires.", responsible_agent=role,
                ))
        test_status = state.get("test_results", {}).get("status")
        if test_status == "not_run":
            issues.append(ReviewIssue(
                severity="medium", category="testing",
                message="No automated tests were executed for this change; behaviour is unverified.",
                suggestion="Add tests or configure a test command for the repository.",
            ))
        elif test_status not in ("passed", None):
            issues.append(ReviewIssue(
                severity="high", category="testing", message=f"Test status is '{test_status}'.",
                suggestion="All required tests must pass before approval.",
            ))
        return issues

    def run(self, state: dict) -> ReviewReport:
        ws = self.rt.workspace()
        diff = ws.diff()
        numstat = ws.numstat()
        fingerprint = diff_hash(diff)
        if not diff.strip():
            return ReviewReport(approved=False, summary="There are no changes to review.",
                                blocking_reasons=["Empty diff"], diff_hash=fingerprint,
                                reviewer_model=self.llm.model_for(self.name))
        automated = self.automated_checks(state, diff, numstat)
        self.log(f"Automated checks produced {len(automated)} findings")
        requirement = state.get("requirement_analysis", {})
        user = (
            f"Requirement: {state.get('user_requirement', '')}\n\n"
            f"Acceptance criteria:\n{to_json(state.get('acceptance_criteria', []), 4_000)}\n\n"
            f"Non-functional requirements: {to_json(requirement.get('non_functional_requirements', []), 2_000)}\n"
            f"Test results: {state.get('test_results', {}).get('summary', 'unknown')}\n\n"
            f"Files and responsible developer: {to_json(state.get('file_ownership', {}), 3_000)}\n\n"
            f"Diff:\n{self.llm.truncate(diff, self.llm.config.context_chars - 15_000)}"
        )
        self.log("Requesting independent LLM review")
        verdict = self.llm.structured(self.name, SYSTEM_PROMPT, user, LLMReview)
        ownership = state.get("file_ownership", {})
        for issue in verdict.issues:
            if issue.responsible_agent == "unknown" and issue.file in ownership:
                issue.responsible_agent = ownership[issue.file]  # type: ignore[assignment]
        blocking = [i for i in automated + verdict.issues if i.severity in BLOCKING_SEVERITIES]
        reasons = [f"[{i.severity}] {i.file or 'general'}: {i.message}" for i in blocking]
        if not verdict.approved:
            reasons.insert(0, f"Reviewer rejected the change: {verdict.summary}")
        approved = verdict.approved and not blocking
        responsible = sorted({i.responsible_agent for i in blocking if i.responsible_agent in ("frontend", "backend")})
        if not approved and not responsible:
            responsible = sorted(set(ownership.values()))
        report = ReviewReport(
            approved=approved, summary=verdict.summary, issues=verdict.issues, automated_findings=automated,
            blocking_reasons=reasons, responsible_agents=responsible, diff_hash=fingerprint,
            reviewer_model=self.llm.model_for(self.name),
        )
        self.log(("Approved" if approved else "Changes requested") + f": {verdict.summary[:300]}",
                 level="info" if approved else "warning")
        return report


def feedback_from_review(report: ReviewReport) -> dict[str, list[str]]:
    feedback: dict[str, list[str]] = {}
    issues = [i for i in report.issues + report.automated_findings if i.severity in BLOCKING_SEVERITIES]
    if not issues:  # rejected without blocking issues: pass all medium findings and the summary
        issues = [i for i in report.issues if i.severity == "medium"]
    for role in report.responsible_agents or ["backend"]:
        items = [
            f"[{i.severity}/{i.category}] {i.file}{':' + str(i.line) if i.line else ''} {i.message} "
            f"Suggestion: {i.suggestion}"
            for i in issues if i.responsible_agent in (role, "unknown")
        ]
        items.append(f"Reviewer summary: {report.summary}")
        feedback[role] = items
    return feedback
