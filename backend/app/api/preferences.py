from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..services import preferences

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class PreferencesUpdate(BaseModel):
    vlm_model: str | None = None


@router.get("")
def get_preferences():
    settings = get_settings()
    prefs = preferences.load()
    return {
        "vlm_model": preferences.get_active_vlm_model(),
        "vlm_model_override": prefs.get("vlm_model"),
        "available_vlm_models": settings.selectable_vlm_models,
        "default_vlm_model": settings.default_vlm_model,
    }


@router.put("")
def update_preferences(body: PreferencesUpdate):
    settings = get_settings()
    prefs = preferences.load()
    if body.vlm_model is not None:
        model = body.vlm_model.strip()
        if not model:
            prefs.pop("vlm_model", None)
        else:
            if model not in settings.selectable_vlm_models:
                raise HTTPException(400, f"unsupported vlm_model: {model}")
            prefs["vlm_model"] = model
    preferences.save(prefs)
    return get_preferences()
