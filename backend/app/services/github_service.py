"""GitHub REST API client.

The access token is held only inside this client (and the git credential
environment of :mod:`repository_service`). It is never logged, never placed in
workflow state, never sent to the frontend and never included in LLM prompts.
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import GitHubError

logger = logging.getLogger(__name__)


def is_protected_branch_name(branch: str, patterns: list[str] | None = None) -> bool:
    patterns = patterns if patterns is not None else get_settings().protected_branch_patterns
    return any(fnmatch.fnmatch(branch, pattern) for pattern in patterns)


class GitHubService:
    def __init__(self, token: str, *, api_url: str | None = None, timeout: float | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        settings = get_settings()
        self._client = httpx.Client(
            base_url=(api_url or settings.github_api_url).rstrip("/"),
            timeout=timeout or settings.github_timeout_seconds,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "DevFlow-AI",
            },
        )

    def close(self) -> None:
        self._client.close()

    # -- low level --------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise GitHubError(f"GitHub API unreachable: {exc}") from exc
        if response.status_code >= 400:
            try:
                body = response.json()
                message = body.get("message", response.text)
                errors = body.get("errors")
            except ValueError:
                message, errors = response.text, None
            hint = {
                401: "GitHub token is invalid or expired.",
                403: "GitHub token lacks permission or rate limit exceeded.",
                404: "Resource not found or token lacks access.",
                422: "GitHub rejected the request.",
            }.get(response.status_code, "GitHub API error.")
            raise GitHubError(
                f"{hint} ({response.status_code}: {message})",
                status=response.status_code,
                details={"errors": errors} if errors else {},
            )
        return response

    def _paginate(self, path: str, params: dict[str, Any] | None = None, limit: int = 300) -> list[dict]:
        params = {"per_page": 100, **(params or {})}
        items: list[dict] = []
        url: str | None = path
        while url and len(items) < limit:
            response = self._request("GET", url, params=params if url == path else None)
            items.extend(response.json())
            url = response.links.get("next", {}).get("url")
        return items[:limit]

    # -- user / repositories ----------------------------------------------------

    def get_authenticated_user(self) -> tuple[dict, list[str]]:
        response = self._request("GET", "/user")
        scopes = [s.strip() for s in response.headers.get("x-oauth-scopes", "").split(",") if s.strip()]
        return response.json(), scopes

    def list_repositories(self) -> list[dict]:
        return self._paginate("/user/repos", {"sort": "updated", "affiliation": "owner,collaborator,organization_member"})

    def get_repository(self, full_name: str) -> dict:
        return self._request("GET", f"/repos/{full_name}").json()

    def list_branches(self, full_name: str) -> list[dict]:
        return self._paginate(f"/repos/{full_name}/branches")

    def branch_exists(self, full_name: str, branch: str) -> bool:
        try:
            self._request("GET", f"/repos/{full_name}/branches/{branch}")
            return True
        except GitHubError as exc:
            if exc.github_status == 404:
                return False
            raise

    def is_branch_protected(self, full_name: str, branch: str) -> bool:
        try:
            data = self._request("GET", f"/repos/{full_name}/branches/{branch}").json()
        except GitHubError as exc:
            if exc.github_status == 404:
                return False
            raise
        return bool(data.get("protected"))

    # -- pull requests ------------------------------------------------------------

    def create_pull_request(self, full_name: str, *, title: str, body: str, head: str, base: str,
                            draft: bool = False) -> dict:
        if head == base:
            raise GitHubError("Refusing to open a pull request from a branch into itself.")
        payload = {"title": title, "body": body, "head": head, "base": base, "draft": draft,
                   "maintainer_can_modify": True}
        return self._request("POST", f"/repos/{full_name}/pulls", json=payload).json()

    def get_pull_request(self, full_name: str, number: int) -> dict:
        return self._request("GET", f"/repos/{full_name}/pulls/{number}").json()

    @staticmethod
    def clone_url(full_name: str) -> str:
        return f"https://github.com/{full_name}.git"
