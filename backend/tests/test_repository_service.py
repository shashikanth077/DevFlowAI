import json
import os

import pytest

from app.core.config import get_settings
from app.core.errors import RepositoryError, UnsafePathError
from app.services.repository_service import RepositoryService, git_auth_env, is_sensitive_path
from tests.conftest import git


@pytest.fixture
def service(tmp_path, monkeypatch):
    settings = get_settings().model_copy(update={"workspace_root": tmp_path / "ws"})
    return RepositoryService(settings)


def test_clone_and_analyze_python_repo(service, remote_repo):
    ws = service.clone(str(remote_repo()), "main", "wf-1", token=None)
    analysis = service.analyze(ws)
    assert analysis.languages["Python"] >= 3
    comp = analysis.components[0]
    assert comp.language == "Python" and comp.has_tests
    assert comp.test_commands == ["python -m pytest -q"]
    assert "pip install --no-cache-dir -r requirements.txt" in comp.install_commands
    assert "tests/test_calc.py" in analysis.test_files
    assert "requirements.txt" in analysis.dependency_files


def test_detects_frontend_and_backend_components(service, remote_repo):
    files = {
        "frontend/package.json": json.dumps({
            "scripts": {"test": "vitest run", "build": "vite build", "lint": "eslint ."},
            "dependencies": {"react": "18"}, "devDependencies": {"vite": "5", "vitest": "1", "typescript": "5"},
        }),
        "frontend/src/App.tsx": "export default function App() { return null }\n",
        "frontend/src/App.test.tsx": "test('x', () => {})\n",
        "backend/requirements.txt": "fastapi\npytest\n",
        "backend/app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        "backend/tests/test_main.py": "def test_ok():\n    assert True\n",
    }
    ws = service.clone(str(remote_repo(files)), "main", "wf-2", token=None)
    analysis = service.analyze(ws)
    kinds = {c.path: c for c in analysis.components}
    assert kinds["frontend"].kind == "frontend"
    assert kinds["frontend"].test_commands == ["npm run test"]
    assert kinds["frontend"].build_commands == ["npm run build"]
    assert "react" in kinds["frontend"].frameworks
    assert kinds["backend"].kind == "backend" and "fastapi" in kinds["backend"].frameworks


def test_path_safety(service, remote_repo):
    ws = service.clone(str(remote_repo()), "main", "wf-3", token=None)
    for bad in ("../outside.txt", "/etc/passwd", ".git/config", "app/../../x", "C:/windows"):
        with pytest.raises(UnsafePathError):
            ws.resolve(bad, for_write=True)
    with pytest.raises(UnsafePathError):
        ws.write_file(".env", "SECRET=1")
    with pytest.raises(UnsafePathError):
        ws.write_file("node_modules/pkg/index.js", "x")
    os.symlink("/etc", ws.root / "link")
    with pytest.raises(UnsafePathError):
        ws.resolve("link/passwd")
    assert ws.read_file(".env") is None
    assert is_sensitive_path("config/.env.production") and not is_sensitive_path(".env.example")


def test_changes_diff_commit_and_push(service, remote_repo):
    remote = remote_repo()
    ws = service.clone(str(remote), "main", "wf-4", token=None)
    ws.write_file("app/new_module.py", "VALUE = 1\n")
    ws.write_file("app/calc.py", ws.read_file("app/calc.py") + "\n\ndef sub(a, b):\n    return a - b\n")
    ws.write_file("scratch.txt", "not approved\n")
    changes = {c["path"]: c["change_type"] for c in ws.changed_files()}
    assert changes == {"app/new_module.py": "created", "app/calc.py": "modified", "scratch.txt": "created"}
    assert "+def sub" in ws.diff() and "+VALUE = 1" in ws.diff()
    assert ws.exists_in_head("app/calc.py") and not ws.exists_in_head("app/new_module.py")

    ws.checkout_new_branch("devflow/feature-x")
    sha = ws.commit(["app/new_module.py", "app/calc.py"], "feat: x", author_name="DevFlow", author_email="d@e.com")
    ws.push("devflow/feature-x", token=None)
    committed = git(remote, "show", "--name-only", "--format=", "devflow/feature-x").split()
    assert sorted(committed) == ["app/calc.py", "app/new_module.py"]  # unapproved file excluded
    assert git(remote, "rev-parse", "devflow/feature-x").strip() == sha
    assert git(remote, "rev-parse", "main").strip() != sha  # base branch untouched
    with pytest.raises(RepositoryError):
        ws.commit([], "empty", author_name="a", author_email="b")


def test_git_auth_env_keeps_token_out_of_args():
    env = git_auth_env("ghp_secret")
    assert env["GIT_CONFIG_KEY_0"] == "http.extraheader"
    assert "ghp_secret" not in env["GIT_CONFIG_VALUE_0"]  # base64 encoded basic auth
    assert git_auth_env(None) == {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}


def test_clone_failure_is_reported(service, tmp_path):
    with pytest.raises(RepositoryError):
        service.clone(str(tmp_path / "missing.git"), "main", "wf-5", token=None)
