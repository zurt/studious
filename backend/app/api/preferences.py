from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..services import learner_profile, preferences

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class PreferencesUpdate(BaseModel):
    vlm_model: str | None = None
    # Learner profile (exercise completions). For each field, None leaves it
    # unchanged and "" clears it back to the default.
    learner_level: str | None = None
    learner_note: str | None = None
    answer_length: str | None = None


@router.get("")
def get_preferences():
    settings = get_settings()
    prefs = preferences.load()
    profile = learner_profile.current()
    return {
        "vlm_model": preferences.get_active_vlm_model(),
        "vlm_model_override": prefs.get("vlm_model"),
        "available_vlm_models": settings.selectable_vlm_models,
        "default_vlm_model": settings.default_vlm_model,
        "learner_level": profile["level"],
        "learner_note": profile["note"],
        "answer_length": profile["answer_length"],
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
    if body.learner_level is not None:
        level = body.learner_level.strip().upper()
        if not level:
            prefs.pop("learner_level", None)
        elif level not in learner_profile.LEVELS:
            raise HTTPException(400, f"learner_level must be one of {list(learner_profile.LEVELS)}")
        else:
            prefs["learner_level"] = level
    if body.learner_note is not None:
        note = body.learner_note.strip()
        if len(note) > learner_profile.MAX_NOTE_LENGTH:
            raise HTTPException(400, f"learner_note is limited to {learner_profile.MAX_NOTE_LENGTH} characters")
        if note:
            prefs["learner_note"] = note
        else:
            prefs.pop("learner_note", None)
    if body.answer_length is not None:
        length = body.answer_length.strip().lower()
        if not length:
            prefs.pop("answer_length", None)
        elif length not in learner_profile.ANSWER_LENGTHS:
            raise HTTPException(400, f"answer_length must be one of {list(learner_profile.ANSWER_LENGTHS)}")
        else:
            prefs["answer_length"] = length
    preferences.save(prefs)
    return get_preferences()
