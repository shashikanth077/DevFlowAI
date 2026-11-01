"""DevFlow AI exposed as an MCP server (stdio), for MCP clients such as Claude Code or Claude Desktop.

It is a thin, authenticated wrapper over the REST API: it can list projects, start a workflow,
and inspect or cancel it. There is **intentionally no approve tool**: the two approval gates
(sandbox execution and push/PR) must be decided by a human in the dashboard, so an AI client
cannot approve its own work.

Configuration (environment):
    DEVFLOW_API_URL    base URL of the API (default http://localhost:8000)
    DEVFLOW_API_TOKEN  a DevFlow access token (JWT) obtained from POST /api/auth/login
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
CANCEL = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)


def create_server(client: httpx.Client) -> MCPServer:
    server = MCPServer(
        "devflow-ai",
        instructions=(
            "Control DevFlow AI, an autonomous multi-agent software engineering platform. Start a workflow with "
            "start_workflow, then poll get_workflow. When status is 'awaiting_approval', a human must approve in the "
            "DevFlow dashboard - there is no approve tool. Pull requests are never merged automatically."
        ),
    )

    def call(method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ToolError(f"Cannot reach the DevFlow API: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ToolError(f"DevFlow API error {response.status_code}: {detail}")
        return response.json()

    @server.tool(annotations=READ)
    def list_projects() -> list[dict[str, Any]]:
        """List the projects (repository + base branch) available to start workflows on."""
        return [
            {"id": p["id"], "name": p["name"], "repository": p["repository"]["full_name"],
             "base_branch": p["base_branch"], "workflows": p["workflow_count"], "last_status": p["last_workflow_status"]}
            for p in call("GET", "/api/projects")
        ]

    @server.tool(annotations=WRITE)
    def start_workflow(project_id: str, requirement: str, base_branch: str | None = None) -> dict[str, Any]:
        """Start an agent workflow that implements `requirement` in the project's repository.
        It runs until the first human approval gate, then waits for a person in the dashboard."""
        body: dict[str, Any] = {"project_id": project_id, "requirement": requirement}
        if base_branch:
            body["base_branch"] = base_branch
        w = call("POST", "/api/workflows/start", json=body)
        return {"workflow_id": w["id"], "status": w["status"], "feature_branch": w["feature_branch"],
                "next": "Poll get_workflow; a human must approve the gates in the dashboard."}

    @server.tool(annotations=READ)
    def list_workflows(limit: int = 10) -> list[dict[str, Any]]:
        """Most recent workflows with their status."""
        rows = call("GET", "/api/workflows", params={"limit": max(1, min(limit, 50))})
        return [{"id": w["id"], "requirement": w["requirement"][:120], "status": w["status"],
                 "stage": w["current_stage"], "pull_request_url": w["pull_request_url"]} for w in rows]

    @server.tool(annotations=READ)
    def get_workflow(workflow_id: str) -> dict[str, Any]:
        """Status, current stage, pending approval, agents, tasks and any error of a workflow."""
        w = call("GET", f"/api/workflows/{workflow_id}")
        pending = w.get("pending_approval")
        return {
            "id": w["id"], "status": w["status"], "stage": w["current_stage"],
            "retry": f"{w['retry_count']}/{w['max_retries']}", "feature_branch": w["feature_branch"],
            "commit_id": w["commit_id"], "pull_request_url": w["pull_request_url"],
            "awaiting_human_approval": (
                {"gate": pending["gate"], "title": pending["title"], "where": "DevFlow dashboard"} if pending else None
            ),
            "agents": [{"agent": a["agent_name"], "attempt": a["attempt"], "status": a["status"]}
                       for a in w["agent_executions"]],
            "tasks": [{"id": t["task_key"], "title": t["title"], "agent": t["assigned_agent"], "status": t["status"]}
                      for t in w["tasks"]],
            "error": (w.get("error_details") or {}).get("message"),
            "traces": w.get("trace_run_ids", []),
        }

    @server.tool(annotations=READ)
    def get_workflow_logs(workflow_id: str, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Workflow log lines after `after_id` (use the last returned id to page)."""
        logs = call("GET", f"/api/workflows/{workflow_id}/logs", params={"after_id": after_id, "limit": limit})
        return [{"id": e["id"], "level": e["level"], "agent": e["agent"], "message": e["message"]} for e in logs]

    @server.tool(annotations=READ)
    def get_workflow_results(workflow_id: str, include_diffs: bool = False) -> dict[str, Any]:
        """Changed files, test runs, review verdicts, MCP tool calls and the pull request of a workflow."""
        r = call("GET", f"/api/workflows/{workflow_id}/results")
        files = []
        for f in r["file_changes"]:
            item = {"path": f["path"], "change": f["change_type"], "additions": f["additions"],
                    "deletions": f["deletions"], "agent": f["agent"]}
            if include_diffs:
                item["diff"] = f["diff"][:6000]
            files.append(item)
        return {
            "status": r["status"], "feature_branch": r["feature_branch"], "pull_request_url": r["pull_request_url"],
            "files": files,
            "tests": [{"round": t["attempt"], "status": t["status"], "summary": t["summary"]} for t in r["test_results"]],
            "reviews": [{"round": v["attempt"], "approved": v["approved"], "summary": v["summary"]}
                        for v in r["review_reports"]],
            "tool_calls": [{"agent": c["agent"], "tool": f"{c['server']}.{c['tool']}", "status": c["status"]}
                           for c in r.get("tool_calls", [])],
        }

    @server.tool(annotations=CANCEL)
    def cancel_workflow(workflow_id: str) -> dict[str, Any]:
        """Request cancellation of a running or waiting workflow."""
        w = call("POST", f"/api/workflows/{workflow_id}/cancel")
        return {"id": w["id"], "status": w["status"], "cancel_requested": w["cancel_requested"]}

    return server


def main() -> None:
    token = os.environ.get("DEVFLOW_API_TOKEN")
    if not token:
        raise SystemExit("DEVFLOW_API_TOKEN is required (get one from POST /api/auth/login)")
    client = httpx.Client(
        base_url=os.environ.get("DEVFLOW_API_URL", "http://localhost:8000").rstrip("/"),
        headers={"Authorization": f"Bearer {token}"}, timeout=60,
    )
    create_server(client).run("stdio")


if __name__ == "__main__":
    main()
