from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import LLMError
from app.database.session import get_db
from app.models import User
from app.schemas.settings import LLMTestResponse, SettingsOut, SettingsUpdate
from app.services.llm_service import LLMService, ProviderError
from app.services.settings_service import apply_update, get_or_create_settings, llm_config_for, to_out

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = get_or_create_settings(db, user.id)
    db.commit()
    return to_out(row)


@router.put("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = get_or_create_settings(db, user.id)
    apply_update(row, body)
    db.commit()
    return to_out(row)


@router.post("/test-llm", response_model=LLMTestResponse)
def test_llm(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Check connectivity to the configured provider and that the model exists."""
    config = llm_config_for(get_or_create_settings(db, user.id))
    try:
        service = LLMService(config)
        models = service.provider.list_models()
    except (LLMError, ProviderError) as exc:
        return LLMTestResponse(ok=False, provider=config.provider, model=config.model, message=str(exc))
    available = config.model in models or any(m.split(":")[0] == config.model for m in models)
    message = "Connected; model available" if available else (
        f"Connected, but model '{config.model}' was not found"
    )
    return LLMTestResponse(ok=available, provider=config.provider, model=config.model, message=message,
                           available_models=models[:100])
