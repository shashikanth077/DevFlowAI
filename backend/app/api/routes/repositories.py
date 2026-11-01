from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models import GitHubRepository, User
from app.schemas.project import RepositoryConnectRequest, RepositoryOut
from app.services.github_service import GitHubService
from app.services.settings_service import require_github_token

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


@router.post("/connect", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
def connect_repository(body: RepositoryConnectRequest, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> GitHubRepository:
    """Verify access to a GitHub repository and register it for use in projects."""
    github = GitHubService(require_github_token(db, user.id))
    try:
        data = github.get_repository(body.full_name)
    finally:
        github.close()
    repo = db.query(GitHubRepository).filter_by(user_id=user.id, full_name=data["full_name"]).one_or_none()
    if repo is None:
        repo = GitHubRepository(user_id=user.id, full_name=data["full_name"])
        db.add(repo)
    repo.owner = data["owner"]["login"]
    repo.name = data["name"]
    repo.default_branch = data.get("default_branch") or "main"
    repo.private = bool(data.get("private"))
    repo.html_url = data["html_url"]
    repo.clone_url = data.get("clone_url") or GitHubService.clone_url(data["full_name"])
    db.commit()
    return repo


@router.get("", response_model=list[RepositoryOut])
def list_connected_repositories(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(GitHubRepository).filter_by(user_id=user.id).order_by(GitHubRepository.full_name).all()
