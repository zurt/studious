from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..services import learner_profile, preferences, tts

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class PreferencesUpdate(BaseModel):
    vlm_model: str | None = None
    # Learner profile (exercise completions). For each field, None leaves it
    # unchanged and "" clears it back to the default.
    learner_level: str | None = None
    learner_note: str | None = None
    answer_length: str | None = None
    # Speech engine for card audio. Strings: None leaves unchanged, "" clears
    # back to the environment default. tts_speaker: None unchanged, "" clears.
    tts_engine: str | None = None
    tts_url: str | None = None
    tts_speaker: int | str | None = None


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
        "tts_engine": tts.engine(),
        "tts_url": tts.url(),
        "tts_speaker": tts.speaker(),
        "tts_engine_override": prefs.get("tts_engine"),
        "tts_default_url": settings.tts_url,
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
    if body.tts_engine is not None:
        eng = body.tts_engine.strip().lower()
        if not eng:
            prefs.pop("tts_engine", None)
        elif eng not in tts.ENGINES:
            raise HTTPException(400, f"tts_engine must be one of {list(tts.ENGINES)}")
        else:
            prefs["tts_engine"] = eng
    if body.tts_url is not None:
        address = body.tts_url.strip()
        if not address:
            prefs.pop("tts_url", None)
        elif not address.lower().startswith(("http://", "https://")) or len(address) > 200:
            raise HTTPException(400, "tts_url must start with http:// or https:// (200 characters at most)")
        else:
            prefs["tts_url"] = address.rstrip("/")
    if body.tts_speaker is not None:
        if body.tts_speaker == "":
            prefs.pop("tts_speaker", None)
        elif isinstance(body.tts_speaker, int) and not isinstance(body.tts_speaker, bool) and body.tts_speaker >= 0:
            prefs["tts_speaker"] = body.tts_speaker
        else:
            raise HTTPException(400, "tts_speaker must be a non-negative style id, or '' to clear")
    preferences.save(prefs)
    tts.reset_cache()
    return get_preferences()
