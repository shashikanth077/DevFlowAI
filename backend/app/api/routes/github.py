from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.errors import GitHubError
from app.core.security import encrypt_secret
from app.database.connection import utcnow
from app.database.session import get_db
from app.models import GitHubConnection, PullRequest, User
from app.schemas.github import GitHubBranch, GitHubConnectRequest, GitHubRepo, GitHubStatus, PullRequestStatus
from app.schemas.workflow import PullRequestOut
from app.services.github_service import GitHubService
from app.services.settings_service import require_github_token

router = APIRouter(prefix="/api/github", tags=["github"])


def _status(db: Session, user: User) -> GitHubStatus:
    conn = db.query(GitHubConnection).filter_by(user_id=user.id).one_or_none()
    if conn:
        return GitHubStatus(connected=True, login=conn.login, scopes=conn.scopes, connected_at=conn.connected_at,
                            source="user")
    if get_settings().github_token:
        return GitHubStatus(connected=True, source="server")
    return GitHubStatus(connected=False)


@router.get("/status", response_model=GitHubStatus)
def github_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _status(db, user)


@router.post("/connect", response_model=GitHubStatus)
def connect_github(body: GitHubConnectRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Validate a personal access token against GitHub and store it encrypted."""
    github = GitHubService(body.token.strip())
    try:
        profile, scopes = github.get_authenticated_user()
    except GitHubError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"GitHub token rejected: {exc.message}") from exc
    finally:
        github.close()
    conn = db.query(GitHubConnection).filter_by(user_id=user.id).one_or_none() or GitHubConnection(user_id=user.id)
    conn.login = profile["login"]
    conn.token_encrypted = encrypt_secret(body.token.strip())
    conn.scopes = scopes
    conn.connected_at = utcnow()
    db.add(conn)
    db.commit()
    return _status(db, user)


@router.delete("/connect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_github(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    db.query(GitHubConnection).filter_by(user_id=user.id).delete()
    db.commit()


@router.get("/repos", response_model=list[GitHubRepo])
def list_github_repos(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    github = GitHubService(require_github_token(db, user.id))
    try:
        repos = github.list_repositories()
    finally:
        github.close()
    return [
        GitHubRepo(full_name=r["full_name"], owner=r["owner"]["login"], name=r["name"], private=bool(r["private"]),
                   default_branch=r.get("default_branch") or "main", html_url=r["html_url"],
                   description=r.get("description"), updated_at=r.get("updated_at"))
        for r in repos
    ]


@router.get("/repos/{owner}/{repo}/branches", response_model=list[GitHubBranch])
def list_branches(owner: str, repo: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    github = GitHubService(require_github_token(db, user.id))
    try:
        branches = github.list_branches(f"{owner}/{repo}")
    finally:
        github.close()
    return [GitHubBranch(name=b["name"], protected=bool(b.get("protected")), sha=b["commit"]["sha"]) for b in branches]


@router.get("/pull-requests", response_model=list[PullRequestOut])
def list_pull_requests(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    return (db.query(PullRequest).filter_by(user_id=user.id).order_by(PullRequest.created_at.desc())
            .limit(limit).all())


@router.get("/pull-requests/{pr_id}/status", response_model=PullRequestStatus)
def pull_request_status(pr_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Refresh a pull request's state from GitHub."""
    pr = db.get(PullRequest, pr_id)
    if pr is None or pr.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pull request not found")
    github = GitHubService(require_github_token(db, user.id))
    try:
        data = github.get_pull_request(pr.repository_full_name, pr.number)
    finally:
        github.close()
    pr.state = data.get("state", pr.state)
    pr.merged = bool(data.get("merged"))
    pr.draft = bool(data.get("draft"))
    db.commit()
    return PullRequestStatus(number=pr.number, url=pr.url, state=pr.state, merged=pr.merged, draft=pr.draft,
                             mergeable_state=data.get("mergeable_state"), title=data.get("title", pr.title))
