"""Agent 1 - Requirement Analyst."""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.schemas.requirement import RequirementAnalysis

SYSTEM_PROMPT = """You are a senior business analyst on a software engineering team.
Analyse the user's software requirement and produce a precise, structured specification.
- Identify the business objectives behind the request.
- Extract functional requirements (give each an id like FR-1) and non-functional requirements
  (performance, security, accessibility, usability, reliability).
- List anything missing or ambiguous as explicit questions, and state the assumptions you make
  so development can proceed.
- Write testable acceptance criteria (Given/When/Then style is welcome).
- Break the work into small development tasks and label each task's area as frontend, backend,
  fullstack or other.
Be concrete. Do not invent features that were not requested."""


class RequirementAnalystAgent(BaseAgent):
    name = "requirement_analyst"

    def run(self, requirement: str, repository_full_name: str = "") -> RequirementAnalysis:
        self.log("Analysing requirement")
        user = f"Target repository: {repository_full_name or 'unknown'}\n\nRequirement:\n{requirement.strip()}"
        analysis = self.llm.structured(self.name, SYSTEM_PROMPT, user, RequirementAnalysis)
        if not analysis.acceptance_criteria:
            analysis.acceptance_criteria = [fr.description for fr in analysis.functional_requirements]
        self.log(
            f"Identified {len(analysis.functional_requirements)} functional requirements, "
            f"{len(analysis.acceptance_criteria)} acceptance criteria and {len(analysis.ambiguities)} open questions"
        )
        return analysis
