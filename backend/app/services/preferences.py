from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import get_settings

log = logging.getLogger("studious.preferences")


def _path() -> Path:
    return get_settings().data_dir / "preferences.json"


def load() -> dict[str, Any]:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8")) or {}
    except Exception as exc:
        log.warning("preferences_load_failed", extra={"error": str(exc)})
        return {}


def save(prefs: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


def get_active_vlm_model() -> str:
    settings = get_settings()
    chosen = load().get("vlm_model")
    if isinstance(chosen, str) and chosen:
        return chosen
    return settings.default_vlm_model
