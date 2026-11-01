from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_project
from app.database.session import get_db
from app.models import GitHubRepository, Project, User
from app.schemas.project import ProjectCreate, ProjectOut, RepositoryOut

router = APIRouter(prefix="/api/projects", tags=["projects"])


def project_out(project: Project) -> ProjectOut:
    workflows = project.workflows
    return ProjectOut(
        id=project.id, name=project.name, description=project.description, base_branch=project.base_branch,
        repository=RepositoryOut.model_validate(project.repository), created_at=project.created_at,
        workflow_count=len(workflows), last_workflow_status=workflows[0].status if workflows else None,
    )


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    repo = db.get(GitHubRepository, body.repository_id)
    if repo is None or repo.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not connected")
    project = Project(user_id=user.id, repository_id=repo.id, name=body.name, description=body.description,
                      base_branch=body.base_branch)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_out(project)


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    projects = db.query(Project).filter_by(user_id=user.id).order_by(Project.created_at.desc()).all()
    return [project_out(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return project_out(get_owned_project(project_id, db, user))
