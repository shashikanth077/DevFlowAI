import httpx

from app.database.session import session_scope
from app.models import GitHubConnection


def test_health(client):
    body = client.get("/health").json()
    assert body["checks"]["database"]["ok"] is True
    assert "sandbox" in body["checks"]


def test_auth_flow(client):
    assert client.post("/api/auth/register", json={"email": "A@x.io", "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "a@x.io", "password": "longenough"}).status_code == 201
    assert client.post("/api/auth/register", json={"email": "A@x.io", "password": "longenough"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "a@x.io", "password": "wrong"}).status_code == 401
    token = client.post("/api/auth/login", json={"email": "a@x.io", "password": "longenough"}).json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == "a@x.io"
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/projects", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_settings_roundtrip_never_returns_api_key(client, auth_headers):
    defaults = client.get("/api/settings", headers=auth_headers).json()
    assert defaults["llm_provider"] == "openai" and defaults["llm_api_key_configured"] is False
    updated = client.put("/api/settings", headers=auth_headers, json={
        "llm_provider": "openai", "llm_model": "gpt-4o-mini", "llm_api_key": "sk-secret-value",
        "agent_models": {"code_reviewer": "gpt-4o", "architect": ""}, "workflow_max_retries": 5,
    }).json()
    assert updated["llm_api_key_configured"] is True
    assert "sk-secret-value" not in str(updated)
    assert updated["agent_models"] == {"code_reviewer": "gpt-4o"}
    assert client.put("/api/settings", headers=auth_headers, json={"llm_temperature": 5}).status_code == 422
    assert client.put("/api/settings", headers=auth_headers, json={"workflow_max_retries": 99}).status_code == 422


def test_test_llm_reports_unreachable_provider(client, auth_headers):
    body = client.post("/api/settings/test-llm", headers=auth_headers).json()
    assert body["ok"] is False and "No API key configured for provider" in body["message"]
    client.put("/api/settings", headers=auth_headers,
               json={"llm_provider": "anthropic", "llm_api_key": "sk-ant-test", "llm_base_url": "http://127.0.0.1:9"})
    body = client.post("/api/settings/test-llm", headers=auth_headers).json()
    assert body["ok"] is False and "Cannot reach" in body["message"]


def test_github_connect_repos_and_branches(client, auth_headers, respx_mock):
    respx_mock.get("https://api.github.com/user").mock(return_value=httpx.Response(
        200, json={"login": "octo"}, headers={"x-oauth-scopes": "repo, read:org"}))
    status = client.post("/api/github/connect", headers=auth_headers, json={"token": "ghp_" + "x" * 36}).json()
    assert status == {"connected": True, "login": "octo", "scopes": ["repo", "read:org"],
                      "connected_at": status["connected_at"], "source": "user"}
    with session_scope() as db:
        stored = db.query(GitHubConnection).one()
        assert "ghp_" not in stored.token_encrypted  # encrypted at rest

    respx_mock.get("https://api.github.com/user/repos").mock(return_value=httpx.Response(200, json=[{
        "full_name": "octo/app", "owner": {"login": "octo"}, "name": "app", "private": True,
        "default_branch": "main", "html_url": "https://github.com/octo/app"}]))
    repos = client.get("/api/github/repos", headers=auth_headers).json()
    assert repos[0]["full_name"] == "octo/app"

    respx_mock.get("https://api.github.com/repos/octo/app/branches").mock(return_value=httpx.Response(200, json=[
        {"name": "main", "protected": True, "commit": {"sha": "abc"}},
        {"name": "dev", "protected": False, "commit": {"sha": "def"}}]))
    branches = client.get("/api/github/repos/octo/app/branches", headers=auth_headers).json()
    assert [b["name"] for b in branches] == ["main", "dev"] and branches[0]["protected"]

    respx_mock.get("https://api.github.com/repos/octo/app").mock(return_value=httpx.Response(200, json={
        "full_name": "octo/app", "owner": {"login": "octo"}, "name": "app", "private": True,
        "default_branch": "main", "html_url": "https://github.com/octo/app",
        "clone_url": "https://github.com/octo/app.git"}))
    repo = client.post("/api/repositories/connect", headers=auth_headers, json={"full_name": "octo/app"})
    assert repo.status_code == 201
    project = client.post("/api/projects", headers=auth_headers, json={
        "name": "App", "repository_id": repo.json()["id"], "base_branch": "main"})
    assert project.status_code == 201 and project.json()["repository"]["full_name"] == "octo/app"
    assert client.post("/api/projects", headers=auth_headers, json={
        "name": "Bad", "repository_id": repo.json()["id"], "base_branch": "bad branch"}).status_code == 422
    assert len(client.get("/api/projects", headers=auth_headers).json()) == 1


def test_github_invalid_token_rejected(client, auth_headers, respx_mock):
    respx_mock.get("https://api.github.com/user").mock(return_value=httpx.Response(401, json={"message": "Bad credentials"}))
    response = client.post("/api/github/connect", headers=auth_headers, json={"token": "ghp_" + "y" * 36})
    assert response.status_code == 400 and "invalid or expired" in response.json()["detail"]


def test_github_not_connected_errors(client, auth_headers):
    response = client.get("/api/github/repos", headers=auth_headers)
    assert response.status_code == 412 and "not connected" in response.json()["detail"]


def test_workflow_validation_and_ownership(client, auth_headers):
    assert client.post("/api/workflows/start", headers=auth_headers,
                       json={"project_id": "x", "requirement": "short"}).status_code == 422
    assert client.post("/api/workflows/start", headers=auth_headers,
                       json={"project_id": "missing", "requirement": "A sufficiently long requirement"}
                       ).status_code == 404
    assert client.get("/api/workflows/unknown", headers=auth_headers).status_code == 404
    assert client.get("/api/workflows", headers=auth_headers).json() == []
    assert client.get("/api/workflows/unknown/events?token=bad").status_code == 401


def test_settings_mcp_preferences_roundtrip(client, auth_headers):
    defaults = client.get("/api/settings", headers=auth_headers).json()
    assert defaults["mcp_enabled"] is False and defaults["mcp_disabled_servers"] == []
    updated = client.put("/api/settings", headers=auth_headers,
                         json={"mcp_enabled": True, "mcp_disabled_servers": ["b", "a", "a"]}).json()
    assert updated["mcp_enabled"] is True and updated["mcp_disabled_servers"] == ["a", "b"]


def test_integrations_status_reports_langsmith_and_mcp(client, auth_headers, tmp_path, monkeypatch):
    status = client.get("/api/integrations/status", headers=auth_headers).json()
    assert status["langsmith"]["enabled"] is False and status["langsmith"]["project"] == "devflow-ai"
    assert "api_key" not in str(status["langsmith"]).lower().replace("api_key_configured", "")
    assert status["mcp"]["available"] is True and status["mcp"]["enabled_for_user"] is False
    builtin = status["mcp"]["servers"][0]
    assert builtin["name"] == "devflow-repo" and builtin["builtin"] and builtin["enabled_for_user"]
    assert "command" not in builtin and "args" not in builtin  # never expose how servers are launched

    servers = tmp_path / "mcp.json"
    servers.write_text('{"mcpServers": {"docs": {"command": "echo", "env": {"TOKEN": "s3cret"}}, "bad name": {}}}')
    from app.core.config import get_settings
    monkeypatch.setattr("app.api.routes.integrations.get_settings",
                        lambda: get_settings().model_copy(update={"mcp_servers_file": str(servers)}))
    client.put("/api/settings", headers=auth_headers, json={"mcp_disabled_servers": ["docs"]})
    status = client.get("/api/integrations/status", headers=auth_headers).json()
    docs = next(s for s in status["mcp"]["servers"] if s["name"] == "docs")
    assert docs["enabled_for_user"] is False and "s3cret" not in str(status)
    assert len(status["mcp"]["config_errors"]) == 1


def test_mcp_diagnostics_connects_and_classifies_tools(client, auth_headers):
    result = client.post("/api/integrations/mcp/test", headers=auth_headers).json()
    server = result["servers"][0]
    assert server["name"] == "devflow-repo" and server["ok"], server
    tools = {t["name"]: t for t in server["tools"]}
    assert set(tools) >= {"read_file", "search_code", "list_directory"}
    assert all(t["read_only"] and t["allowed"] for t in tools.values())
    assert tools["read_file"]["parameters"] == ["path", "start_line", "end_line"]


def test_langsmith_connection_test_without_key(client, auth_headers):
    body = client.post("/api/integrations/langsmith/test", headers=auth_headers).json()
    assert body["ok"] is False and "LANGSMITH_API_KEY" in body["message"]
    assert client.post("/api/integrations/langsmith/test").status_code == 401


def test_schema_status_flags_missing_migrations(tmp_path):
    """A database created without running `alembic upgrade head` must be reported, not left to 500."""
    from app.database.connection import build_engine
    from app.database.schema import schema_status

    engine = build_engine(f"sqlite:///{tmp_path / 'stale.db'}")
    status = schema_status(engine)
    assert status["ok"] is False and status["current"] is None
    assert status["head"] == "0003" and "alembic upgrade head" in status["message"]


def test_health_reports_schema(client):
    body = client.get("/health").json()
    assert "schema" in body["checks"]


def test_legacy_ollama_settings_are_mapped_to_claude(client, auth_headers):
    """Rows saved before Ollama was removed must not break the Settings page."""
    from app.database.session import session_scope
    from app.models import UserSettings

    client.get("/api/settings", headers=auth_headers)  # create the row
    with session_scope() as db:
        row = db.query(UserSettings).one()
        row.llm_provider, row.llm_model = "ollama", "llama3.1:8b"
    body = client.get("/api/settings", headers=auth_headers)
    assert body.status_code == 200
    assert body.json()["llm_provider"] == "anthropic" and body.json()["llm_model"] == "claude-sonnet-5-5"
