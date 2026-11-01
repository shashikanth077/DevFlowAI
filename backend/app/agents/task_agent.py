"""Agent 4 - Task Orchestrator (planning half).

The LLM proposes development tasks; this module then *validates* the plan
deterministically: unique ids, known dependencies, no cycles, an agent that
exists for the repository, and a topological execution order. The execution
half of orchestration (routing, retries, parallelism) lives in
:mod:`app.orchestration`.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque

from app.agents.base import BaseAgent, infer_area, to_json
from app.schemas.task import PlannedTask, TaskPlan, TaskState

SYSTEM_PROMPT = """You are the engineering lead orchestrating a team of AI developers.
Turn the architecture plan into small, independently verifiable development tasks.
Rules:
- assigned_agent is "frontend" for UI/client code and "backend" for server/API/data code.
- Each task lists the exact target_files (repository-relative paths) it creates or modifies.
- dependencies reference other task ids that must be finished first (e.g. the UI that calls an API
  depends on the backend task that implements it).
- Include writing/updating tests inside the task that changes the code.
- Use ids T1, T2, ...; keep the list short (typically 1-6 tasks)."""


def _topological_order(tasks: list[TaskState]) -> tuple[list[TaskState], list[str]]:
    """Kahn's algorithm. Returns ordered tasks and dependency edges removed to break cycles."""
    by_id = {t.id: t for t in tasks}
    indegree = {t.id: 0 for t in tasks}
    children: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        for dep in task.dependencies:
            indegree[task.id] += 1
            children[dep].append(task.id)
    queue = deque(t.id for t in tasks if indegree[t.id] == 0)
    ordered: list[str] = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    removed: list[str] = []
    if len(ordered) < len(tasks):  # cycle: drop remaining dependencies of unresolved tasks
        for task_id in (t.id for t in tasks if t.id not in ordered):
            task = by_id[task_id]
            removed += [f"{task_id}->{d}" for d in task.dependencies if d not in ordered]
            task.dependencies = [d for d in task.dependencies if d in ordered]
            ordered.append(task_id)
    return [by_id[i] for i in ordered], removed


class TaskOrchestratorAgent(BaseAgent):
    name = "task_orchestrator"

    def run(self, state: dict) -> list[TaskState]:
        repo = state["repository_analysis"]
        components = repo.get("components", [])
        available = {c["kind"] for c in components if c.get("kind") in ("frontend", "backend")}
        plan = state["architecture_plan"]
        user = (
            f"Requirement summary: {state['requirement_analysis'].get('summary', '')}\n"
            f"Acceptance criteria: {to_json(state.get('acceptance_criteria', []), 4_000)}\n\n"
            f"Architecture plan:\n{to_json(plan, 15_000)}\n\n"
            f"Repository components: {to_json(components, 3_000)}\n"
            f"Available development agents: {sorted(available) or ['backend']}"
        )
        self.log("Planning development tasks")
        proposed = self.llm.structured(self.name, SYSTEM_PROMPT, user, TaskPlan).tasks
        if not proposed:
            proposed = self._tasks_from_file_plan(plan)
            self.log("Model returned no tasks; derived tasks from the architecture file plan", level="warning")
        tasks = self._validate(proposed, components, available)
        ordered, removed = _topological_order(tasks)
        if removed:
            self.log(f"Removed cyclic dependencies: {', '.join(removed)}", level="warning")
        for index, task in enumerate(ordered):
            task.position = index
        self.log(
            "Planned tasks: " + "; ".join(f"{t.id} [{t.assigned_agent}] {t.title}" for t in ordered)
        )
        return ordered

    @staticmethod
    def _tasks_from_file_plan(plan: dict) -> list[PlannedTask]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for item in plan.get("file_plan", []):
            grouped[item.get("area", "backend")].append(item)
        tasks: list[PlannedTask] = []
        for index, area in enumerate(sorted(grouped, key=lambda a: a != "backend"), start=1):
            items = grouped[area]
            tasks.append(PlannedTask(
                id=f"T{index}",
                title=f"Implement {area} changes",
                description="\n".join(f"{i['action']} {i['path']}: {i.get('description', '')}" for i in items),
                assigned_agent=area,
                dependencies=["T1"] if index > 1 else [],
                target_files=[i["path"] for i in items],
            ))
        return tasks

    def _validate(self, proposed: list[PlannedTask], components: list[dict], available: set[str]) -> list[TaskState]:
        tasks: list[TaskState] = []
        seen: set[str] = set()
        id_map: dict[str, str] = {}
        for index, item in enumerate(proposed, start=1):
            task_id = re.sub(r"[^A-Za-z0-9_-]", "", item.id)[:20] or f"T{index}"
            while task_id in seen:
                task_id = f"{task_id}_{index}"
            seen.add(task_id)
            id_map[item.id] = task_id
            role = item.assigned_agent
            areas = {infer_area(f, components) for f in item.target_files} - {None}
            if len(areas) == 1:
                role = areas.pop()  # file locations are the strongest signal
            if available and role not in available:
                role = next(iter(sorted(available)))
                self.log(f"Task {task_id} reassigned to {role} (no {item.assigned_agent} component)", level="warning")
            tasks.append(TaskState(
                id=task_id, title=item.title[:300], description=item.description,
                assigned_agent=role, dependencies=list(item.dependencies),
                target_files=[f.strip().removeprefix("./") for f in item.target_files if f.strip()],
                acceptance_criteria=item.acceptance_criteria,
            ))
        for task in tasks:
            task.dependencies = [id_map.get(d, d) for d in task.dependencies]
            task.dependencies = [d for d in dict.fromkeys(task.dependencies) if d in seen and d != task.id]
        return tasks
