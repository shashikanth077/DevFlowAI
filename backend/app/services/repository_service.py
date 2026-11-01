"""Git workspace management and deterministic repository inspection.

Every workflow gets its own isolated clone under ``WORKSPACE_ROOT/<workflow_id>``.
All file access performed on behalf of an agent goes through
:class:`Workspace`, which rejects path traversal, symlink escapes, writes into
``.git`` and access to credential files.
"""

from __future__ import annotations

import base64
import fnmatch
import json
import logging
import os
import re
import shutil
import subprocess
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath

from app.core.config import Settings, get_settings
from app.core.errors import RepositoryError, UnsafePathError
from app.schemas.repository import ProjectComponent, RepositoryAnalysis

logger = logging.getLogger(__name__)

IGNORED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".next", ".nuxt",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage", ".idea", ".vscode", ".tox", "target",
    ".turbo", ".cache", ".gradle", "vendor", ".svelte-kit", "htmlcov", ".eggs",
}
SENSITIVE_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "*.p12", "*.pfx", "*.keystore",
    "*.jks", ".npmrc", ".pypirc", ".netrc", "credentials", "credentials.*", "secrets.*", "*.kdbx",
]
SENSITIVE_ALLOWLIST = [".env.example", ".env.sample", ".env.template"]
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".pdf", ".zip", ".gz", ".tar", ".jar",
    ".exe", ".dll", ".so", ".dylib", ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".mov", ".pyc",
    ".class", ".o", ".a", ".db", ".sqlite", ".wasm", ".lock",
}
LANGUAGE_BY_EXTENSION = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby",
    ".rs": "Rust", ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C", ".swift": "Swift", ".vue": "Vue",
    ".svelte": "Svelte", ".css": "CSS", ".scss": "SCSS", ".html": "HTML", ".sql": "SQL", ".sh": "Shell",
}
CONFIG_FILE_PATTERNS = [
    "package.json", "tsconfig*.json", "vite.config.*", "vitest.config.*", "jest.config.*", "next.config.*",
    "pyproject.toml", "requirements*.txt", "setup.py", "setup.cfg", "pytest.ini", "tox.ini", "alembic.ini",
    "Dockerfile", "docker-compose*.yml", "docker-compose*.yaml", ".eslintrc*", "eslint.config.*",
    ".prettierrc*", "go.mod", "pom.xml", "build.gradle*", "Makefile", "manage.py",
]
TEST_FILE_RE = re.compile(
    r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|\.(test|spec)\.(t|j)sx?$"
)
_DEFAULT_NPM_TEST = "no test specified"


def git_auth_env(token: str | None) -> dict[str, str]:
    """Credentials for git over HTTPS, passed via environment (never argv or .git/config)."""
    env = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        })
    return env


def _scrub(text: str, token: str | None) -> str:
    if token:
        text = text.replace(token, "***")
        text = text.replace(base64.b64encode(f"x-access-token:{token}".encode()).decode(), "***")
    return text


def run_git(args: list[str], cwd: Path | None, *, token: str | None = None, timeout: int = 300,
            check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **git_auth_env(token)}
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RepositoryError(f"git {args[0]} timed out after {timeout}s") from exc
    if check and result.returncode != 0:
        raise RepositoryError(
            f"git {args[0]} failed: {_scrub(result.stderr.strip() or result.stdout.strip(), token)[:2000]}"
        )
    return result


def is_sensitive_path(rel_path: str) -> bool:
    name = PurePosixPath(rel_path).name
    if name in SENSITIVE_ALLOWLIST:
        return False
    return any(fnmatch.fnmatch(name, pattern) for pattern in SENSITIVE_PATTERNS)


class Workspace:
    """A cloned repository on disk with guarded file access."""

    def __init__(self, root: Path, *, max_file_bytes: int = 200_000) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes

    # -- path safety ---------------------------------------------------------------

    def normalize(self, rel_path: str) -> str:
        rel_path = rel_path.strip().replace("\\", "/")
        while rel_path.startswith("./"):
            rel_path = rel_path[2:]
        if not rel_path or rel_path.startswith("/") or re.match(r"^[A-Za-z]:", rel_path):
            raise UnsafePathError(f"Path must be relative to the repository: {rel_path!r}")
        parts = PurePosixPath(rel_path).parts
        if ".." in parts:
            raise UnsafePathError(f"Path traversal is not allowed: {rel_path!r}")
        if parts and parts[0] == ".git":
            raise UnsafePathError("Access to .git is not allowed")
        return str(PurePosixPath(*parts))

    def resolve(self, rel_path: str, *, for_write: bool = False) -> Path:
        normalized = self.normalize(rel_path)
        if is_sensitive_path(normalized):
            raise UnsafePathError(f"Access to credential-like file is blocked: {normalized}")
        target = (self.root / normalized).resolve()
        if target != self.root and self.root not in target.parents:
            raise UnsafePathError(f"Path escapes the workspace: {rel_path!r}")
        if for_write and any(part in IGNORED_DIRS for part in PurePosixPath(normalized).parts[:-1]):
            raise UnsafePathError(f"Writing into generated/vendor directory is not allowed: {normalized}")
        return target

    # -- file access -----------------------------------------------------------------

    def exists(self, rel_path: str) -> bool:
        try:
            return self.resolve(rel_path).is_file()
        except UnsafePathError:
            return False

    def read_file(self, rel_path: str, *, max_bytes: int | None = None) -> str | None:
        """Return text content, or ``None`` if missing, binary, blocked or too large."""
        try:
            path = self.resolve(rel_path)
        except UnsafePathError:
            return None
        if not path.is_file() or path.suffix.lower() in BINARY_EXTENSIONS:
            return None
        if path.stat().st_size > (max_bytes or self.max_file_bytes):
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

    def write_file(self, rel_path: str, content: str) -> Path:
        path = self.resolve(rel_path, for_write=True)
        if len(content.encode()) > self.max_file_bytes:
            raise UnsafePathError(f"Generated content for {rel_path} exceeds {self.max_file_bytes} bytes")
        if path.is_symlink():
            raise UnsafePathError(f"Refusing to write through a symlink: {rel_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if content and not content.endswith("\n"):
            content += "\n"
        path.write_text(content, encoding="utf-8")
        return path

    def list_files(self, limit: int = 5000) -> list[str]:
        files: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS and not d.endswith(".egg-info"))
            for filename in sorted(filenames):
                rel = os.path.relpath(os.path.join(dirpath, filename), self.root).replace(os.sep, "/")
                files.append(rel)
                if len(files) >= limit:
                    return files
        return files

    # -- git ------------------------------------------------------------------------

    def git(self, *args: str, token: str | None = None, timeout: int = 300, check: bool = True) -> str:
        return run_git(list(args), self.root, token=token, timeout=timeout, check=check).stdout

    def head_commit(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def exists_in_head(self, rel_path: str) -> bool:
        return run_git(["cat-file", "-e", f"HEAD:{self.normalize(rel_path)}"], self.root, check=False).returncode == 0

    def current_branch(self) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def _mark_untracked(self) -> None:
        untracked = [p for p in self.git("ls-files", "--others", "--exclude-standard", "-z").split("\0") if p]
        if untracked:
            self.git("add", "--intent-to-add", "--", *untracked)

    def changed_files(self) -> list[dict[str, str]]:
        """Files changed relative to HEAD (including new files)."""
        self._mark_untracked()
        out: list[dict[str, str]] = []
        for line in self.git("diff", "--name-status", "HEAD").splitlines():
            status, _, path = line.partition("\t")
            change_type = {"A": "created", "D": "deleted"}.get(status[:1], "modified")
            out.append({"path": path, "change_type": change_type})
        # Intent-to-add files show as "A" only with --cached; detect them explicitly.
        new_files = set(self.git("diff", "--name-only", "--diff-filter=A", "HEAD").splitlines())
        for item in out:
            if item["path"] in new_files:
                item["change_type"] = "created"
        return out

    def diff(self, paths: list[str] | None = None) -> str:
        self._mark_untracked()
        args = ["diff", "HEAD", "--no-color"]
        if paths:
            args += ["--", *paths]
        return self.git(*args)

    def numstat(self) -> dict[str, tuple[int, int]]:
        self._mark_untracked()
        stats: dict[str, tuple[int, int]] = {}
        for line in self.git("diff", "HEAD", "--numstat").splitlines():
            added, deleted, path = line.split("\t", 2)
            stats[path] = (int(added) if added.isdigit() else 0, int(deleted) if deleted.isdigit() else 0)
        return stats

    def checkout_new_branch(self, branch: str) -> None:
        self.git("checkout", "-b", branch)

    def commit(self, paths: list[str], message: str, *, author_name: str, author_email: str) -> str:
        if not paths:
            raise RepositoryError("No approved files to commit")
        self.git("reset", "-q")  # clear intent-to-add entries; stage only approved files
        for path in paths:
            self.normalize(path)
        self.git("add", "--", *paths)
        staged = [p for p in self.git("diff", "--cached", "--name-only").splitlines() if p]
        if not staged:
            raise RepositoryError("Nothing to commit: approved files have no changes")
        self.git(
            "-c", f"user.name={author_name}", "-c", f"user.email={author_email}",
            "commit", "-m", message,
        )
        return self.head_commit()

    def push(self, branch: str, *, token: str | None, remote: str = "origin") -> None:
        self.git("push", remote, f"HEAD:refs/heads/{branch}", token=token, timeout=600)


class RepositoryService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def workspace_dir(self, workflow_id: str) -> Path:
        return (Path(self.settings.workspace_root) / workflow_id).resolve()

    def open(self, workflow_id: str) -> Workspace:
        path = self.workspace_dir(workflow_id) / "repo"
        if not (path / ".git").exists():
            raise RepositoryError("Workspace not found; the repository must be cloned first")
        return Workspace(path, max_file_bytes=self.settings.max_file_bytes)

    def clone(self, clone_url: str, base_branch: str, workflow_id: str, *, token: str | None) -> Workspace:
        target = self.workspace_dir(workflow_id) / "repo"
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        run_git(
            ["clone", "--branch", base_branch, "--single-branch", "--no-tags", clone_url, str(target)],
            None, token=token, timeout=900,
        )
        logger.info("Repository cloned", extra={"workflow_id": workflow_id, "branch": base_branch})
        return Workspace(target, max_file_bytes=self.settings.max_file_bytes)

    def cleanup(self, workflow_id: str) -> None:
        path = self.workspace_dir(workflow_id)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    # -- analysis -------------------------------------------------------------------

    def analyze(self, ws: Workspace) -> RepositoryAnalysis:
        files = ws.list_files()
        languages = Counter(
            LANGUAGE_BY_EXTENSION[Path(f).suffix.lower()]
            for f in files
            if Path(f).suffix.lower() in LANGUAGE_BY_EXTENSION
        )
        components = self._detect_components(ws, files)
        frameworks = sorted({fw for c in components for fw in c.frameworks})
        dependency_files = [
            f for f in files
            if Path(f).name in {"package.json", "requirements.txt", "pyproject.toml", "setup.py", "go.mod",
                                "pom.xml", "Pipfile", "requirements-dev.txt", "Gemfile", "Cargo.toml"}
        ]
        config_files = [f for f in files if any(fnmatch.fnmatch(Path(f).name, p) for p in CONFIG_FILE_PATTERNS)]
        test_files = [f for f in files if TEST_FILE_RE.search(f)]
        return RepositoryAnalysis(
            total_files=len(files),
            file_tree=self._tree(files),
            languages=dict(languages.most_common()),
            frameworks=frameworks,
            components=components,
            dependency_files=dependency_files,
            test_files=test_files[:300],
            config_files=config_files[:100],
            head_commit=ws.head_commit(),
        )

    @staticmethod
    def _tree(files: list[str], limit: int = 600) -> str:
        shown = files[:limit]
        tree = "\n".join(shown)
        if len(files) > limit:
            tree += f"\n... ({len(files) - limit} more files)"
        return tree

    def _detect_components(self, ws: Workspace, files: list[str]) -> list[ProjectComponent]:
        markers = {"package.json", "requirements.txt", "pyproject.toml", "setup.py", "go.mod"}
        dirs: dict[str, set[str]] = {}
        for f in files:
            p = PurePosixPath(f)
            if p.name in markers and len(p.parts) <= 3:
                dirs.setdefault(str(p.parent), set()).add(p.name)
        components: list[ProjectComponent] = []
        for directory in sorted(dirs, key=lambda d: (d != ".", d)):
            present = dirs[directory]
            prefix = "" if directory == "." else directory + "/"
            component_files = [f for f in files if f.startswith(prefix)] if prefix else files
            if "package.json" in present:
                comp = self._node_component(ws, directory, prefix, component_files)
                if comp:
                    components.append(comp)
            if present & {"requirements.txt", "pyproject.toml", "setup.py"}:
                components.append(self._python_component(ws, directory, prefix, present, component_files))
            if "go.mod" in present:
                components.append(ProjectComponent(
                    path=directory, kind="backend", language="Go", frameworks=["go"],
                    package_manager="go", install_commands=["go mod download"], test_commands=["go test ./..."],
                    build_commands=["go build ./..."], sandbox_image="golang:1.22",
                    has_tests=any(f.endswith("_test.go") for f in component_files),
                ))
        return components

    def _node_component(self, ws: Workspace, directory: str, prefix: str, files: list[str]) -> ProjectComponent | None:
        raw = ws.read_file(prefix + "package.json")
        if raw is None:
            return None
        try:
            pkg = json.loads(raw)
        except json.JSONDecodeError:
            return None
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        scripts: dict[str, str] = pkg.get("scripts", {}) or {}
        known = {
            "react": "react", "next": "next.js", "vue": "vue", "@angular/core": "angular", "svelte": "svelte",
            "express": "express", "@nestjs/core": "nestjs", "fastify": "fastify", "koa": "koa", "vite": "vite",
            "jest": "jest", "vitest": "vitest", "typescript": "typescript", "@mui/material": "material-ui",
            "@reduxjs/toolkit": "redux-toolkit", "eslint": "eslint", "prisma": "prisma", "mocha": "mocha",
        }
        frameworks = sorted({name for dep, name in known.items() if dep in deps})
        frontend = {"react", "next.js", "vue", "angular", "svelte"}
        backend = {"express", "nestjs", "fastify", "koa"}
        kind = "frontend" if frontend & set(frameworks) else "backend" if backend & set(frameworks) else "library"
        if (ws.root / prefix / "pnpm-lock.yaml").exists():
            manager, install = "pnpm", ["corepack enable", "pnpm install --frozen-lockfile"]
        elif (ws.root / prefix / "yarn.lock").exists():
            manager, install = "yarn", ["yarn install --frozen-lockfile"]
        elif (ws.root / prefix / "package-lock.json").exists():
            manager, install = "npm", ["npm ci --no-audit --no-fund"]
        else:
            manager, install = "npm", ["npm install --no-audit --no-fund"]
        run = "npm run" if manager == "npm" else f"{manager} run"
        test_script = scripts.get("test", "")
        tests = [f"{run} test"] if test_script and _DEFAULT_NPM_TEST not in test_script else []
        return ProjectComponent(
            path=directory,
            kind=kind,
            language="TypeScript" if "typescript" in deps or (ws.root / prefix / "tsconfig.json").exists() else "JavaScript",
            frameworks=frameworks,
            package_manager=manager,
            install_commands=install,
            test_commands=tests,
            lint_commands=[f"{run} lint"] if "lint" in scripts else [],
            build_commands=[f"{run} build"] if "build" in scripts else [],
            sandbox_image=self.settings.sandbox_node_image,
            has_tests=bool(tests) and any(TEST_FILE_RE.search(f) for f in files),
        )

    def _python_component(self, ws: Workspace, directory: str, prefix: str, present: set[str],
                          files: list[str]) -> ProjectComponent:
        dep_text = ""
        install: list[str] = []
        for req in ("requirements.txt", "requirements-dev.txt"):
            content = ws.read_file(prefix + req)
            if content is not None:
                dep_text += content.lower()
                install.append(f"pip install --no-cache-dir -r {req}")
        if "pyproject.toml" in present:
            content = ws.read_file(prefix + "pyproject.toml") or ""
            dep_text += content.lower()
            if not install:
                extras = ""
                try:
                    data = tomllib.loads(content)
                    optional = data.get("project", {}).get("optional-dependencies", {})
                    if "dev" in optional:
                        extras = "[dev]"
                    elif "test" in optional:
                        extras = "[test]"
                except tomllib.TOMLDecodeError:
                    pass
                install.append(f'pip install --no-cache-dir -e ".{extras}"')
        elif "setup.py" in present and not install:
            install.append("pip install --no-cache-dir -e .")
        known = {"fastapi": "fastapi", "django": "django", "flask": "flask", "sqlalchemy": "sqlalchemy",
                 "pydantic": "pydantic", "pytest": "pytest", "celery": "celery", "langgraph": "langgraph",
                 "ruff": "ruff", "flake8": "flake8"}
        frameworks = sorted({name for key, name in known.items() if re.search(rf"\b{key}\b", dep_text)})
        has_tests = any(f.endswith(".py") and TEST_FILE_RE.search(f) for f in files)
        if has_tests and "pytest" not in frameworks:
            install.append("pip install --no-cache-dir pytest")
        web = {"fastapi", "django", "flask"}
        return ProjectComponent(
            path=directory,
            kind="backend" if web & set(frameworks) else "library",
            language="Python",
            frameworks=frameworks,
            package_manager="pip",
            install_commands=install,
            test_commands=["python -m pytest -q"] if has_tests else [],
            lint_commands=["ruff check ."] if "ruff" in frameworks else ["flake8"] if "flake8" in frameworks else [],
            build_commands=[],
            sandbox_image=self.settings.sandbox_python_image,
            has_tests=has_tests,
        )
