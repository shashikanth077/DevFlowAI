"""FastAPI dependencies: database session and authenticated user."""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.session import get_db
from app.models import Project, User, WorkflowExecution

bearer = HTTPBearer(auto_error=False)


def _user_from_token(token: str, db: Session) -> User:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"}) from exc
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return _user_from_token(credentials.credentials, db)


def get_stream_user(token: str = Query(..., description="Access token (EventSource cannot send headers)"),
                    db: Session = Depends(get_db)) -> User:
    return _user_from_token(token, db)


def get_owned_project(project_id: str, db: Session, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def get_owned_workflow(workflow_id: str, db: Session, user: User) -> WorkflowExecution:
    workflow = db.get(WorkflowExecution, workflow_id)
    if workflow is None or workflow.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    return workflow
