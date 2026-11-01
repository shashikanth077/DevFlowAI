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
    assert defaults["llm_provider"] == "ollama" and defaults["llm_api_key_configured"] is False
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
    client.put("/api/settings", headers=auth_headers, json={"llm_base_url": "http://127.0.0.1:9"})
    body = client.post("/api/settings/test-llm", headers=auth_headers).json()
    assert body["ok"] is False and "Ollama" in body["message"]


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
