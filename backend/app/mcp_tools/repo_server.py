"""DevFlow repository tools exposed as an MCP server (stdio).

Gives agents on-demand, read-only access to the cloned repository instead of stuffing whole files
into prompts. It is launched per workflow with ``--workspace <path>`` and reuses
:class:`Workspace`, so path traversal, ``.git`` access, credential files (``.env``, keys, ...),
binary files and oversized files are all refused exactly as for the agents' own file access.
Every tool is annotated ``readOnlyHint`` and none of them modifies the repository or its index.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from app.core.errors import RepositoryError, UnsafePathError
from app.services.repository_service import IGNORED_DIRS, Workspace, is_sensitive_path

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
MAX_READ_LINES = 400
MAX_OUTPUT_CHARS = 20_000
SEARCH_TIME_BUDGET_S = 10.0


def create_server(workspace: Workspace) -> MCPServer:
    server = MCPServer(
        "devflow-repo",
        instructions="Read-only tools for exploring the repository a DevFlow AI workflow is working on.",
    )

    def safe(path: str, *, must_exist: bool = True) -> Path:
        try:
            resolved = workspace.resolve(path)
        except UnsafePathError as exc:
            raise ToolError(exc.message) from exc
        if must_exist and not resolved.exists():
            raise ToolError(f"Path not found: {path}")
        return resolved

    @server.tool(annotations=READ_ONLY)
    def list_directory(path: str = ".") -> str:
        """List files and sub-directories of a repository directory (ignores vendor/build folders)."""
        target = safe(path)
        if not target.is_dir():
            raise ToolError(f"Not a directory: {path}")
        rows = []
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if entry.is_dir() and entry.name in IGNORED_DIRS:
                continue
            rel = entry.relative_to(workspace.root).as_posix()
            if entry.is_file() and is_sensitive_path(rel):
                continue
            rows.append(f"{rel}/" if entry.is_dir() else rel)
        return "\n".join(rows[:500]) or "(empty directory)"

    @server.tool(annotations=READ_ONLY)
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read a text file with line numbers (max 400 lines per call; use start_line/end_line to page)."""
        safe(path)
        text = workspace.read_file(path)
        if text is None:
            raise ToolError(f"Cannot read {path}: missing, binary, too large or a protected file")
        lines = text.splitlines()
        start = max(1, start_line)
        end = min(len(lines), end_line or start + MAX_READ_LINES - 1, start + MAX_READ_LINES - 1)
        body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
        suffix = f"\n... ({len(lines) - end} more lines)" if end < len(lines) else ""
        return f"{path} (lines {start}-{end} of {len(lines)})\n{body}{suffix}"[:MAX_OUTPUT_CHARS]

    @server.tool(annotations=READ_ONLY)
    def search_code(query: str, glob: str | None = None, regex: bool = False, ignore_case: bool = True,
                    max_results: int = 40) -> str:
        """Search file contents. Literal match by default; set regex=true for a regular expression.
        `glob` filters by file name or path (for example '*.py' or 'src/**/*.tsx')."""
        if not query or len(query) > 300:
            raise ToolError("query must be 1-300 characters")
        flags = re.IGNORECASE if ignore_case else 0
        try:
            pattern = re.compile(query if regex else re.escape(query), flags)
        except re.error as exc:
            raise ToolError(f"Invalid regular expression: {exc}") from exc
        deadline = time.monotonic() + SEARCH_TIME_BUDGET_S
        hits: list[str] = []
        limit = max(1, min(max_results, 200))
        for rel in workspace.list_files():
            if glob and not (fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(Path(rel).name, glob)):
                continue
            content = workspace.read_file(rel)
            if content is None:
                continue
            for number, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(f"{rel}:{number}: {line.strip()[:200]}")
                    if len(hits) >= limit:
                        return "\n".join(hits) + f"\n(stopped after {limit} results)"
            if time.monotonic() > deadline:
                return "\n".join(hits) + "\n(search time budget exhausted; narrow the query or glob)"
        return "\n".join(hits) or "No matches."

    @server.tool(annotations=READ_ONLY)
    def git_log(path: str | None = None, max_count: int = 10) -> str:
        """Recent commit history, optionally for one file."""
        args = ["log", f"--max-count={max(1, min(max_count, 50))}", "--date=short", "--pretty=format:%h %ad %an  %s"]
        if path:
            safe(path, must_exist=False)
            args += ["--", path]
        try:
            return workspace.git(*args) or "(no commits)"
        except RepositoryError as exc:
            raise ToolError(exc.message) from exc

    @server.tool(annotations=READ_ONLY)
    def git_status() -> str:
        """Files changed in the workspace relative to HEAD (porcelain format)."""
        try:
            return workspace.git("status", "--porcelain", "--untracked-files=all") or "(clean)"
        except RepositoryError as exc:
            raise ToolError(exc.message) from exc

    @server.tool(annotations=READ_ONLY)
    def git_diff(path: str) -> str:
        """Unified diff of one tracked file against HEAD. (For new files use read_file.)"""
        safe(path, must_exist=False)
        try:
            out = workspace.git("diff", "HEAD", "--no-color", "--", path)
        except RepositoryError as exc:
            raise ToolError(exc.message) from exc
        return out[:MAX_OUTPUT_CHARS] or "(no changes to this tracked file)"

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="DevFlow repository MCP server (stdio)")
    parser.add_argument("--workspace", required=True, help="Path of the cloned repository")
    args = parser.parse_args()
    root = Path(args.workspace)
    if not root.is_dir():
        raise SystemExit(f"Workspace not found: {root}")
    create_server(Workspace(root)).run("stdio")


if __name__ == "__main__":
    main()
