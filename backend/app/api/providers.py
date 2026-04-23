from __future__ import annotations

from fastapi import APIRouter

from ..config import get_settings
from ..providers import registry

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
def list_providers():
    settings = get_settings()
    ocr_infos = []
    for name in registry.list_ocr():
        try:
            info = registry.get_ocr(name).info()
        except Exception as exc:
            info = {"name": name, "kind": "ocr", "unavailable": str(exc)}
        ocr_infos.append(info)
    vlm_infos = []
    for name in registry.list_vlm():
        try:
            info = registry.get_vlm(name).info()
        except Exception as exc:
            info = {"name": name, "kind": "vlm", "unavailable": str(exc)}
        vlm_infos.append(info)
    return {
        "ocr": ocr_infos,
        "vlm": vlm_infos,
        "defaults": {
            "ocr": "tesseract",
            "vlm": "anthropic",
            "vlm_model": settings.default_vlm_model,
            "vlm_prompt": settings.default_vlm_prompt,
        },
    }
