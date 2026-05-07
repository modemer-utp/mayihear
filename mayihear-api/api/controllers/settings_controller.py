from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from infrastructure.utilities import secret_manager
from api.controllers import transcription_controller, insights_controller, meeting_act_controller

router = APIRouter(prefix="/settings", tags=["settings"])


class ApiKeysRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    monday_token: Optional[str] = None
    monday_board_id: Optional[str] = None
    monday_column_id: Optional[str] = None
    transcription_mode: Optional[str] = None   # "gemini" | "local"
    whisper_model: Optional[str] = None        # "tiny" | "small" | "medium" | "large-v3"
    vertex_sa_path: Optional[str] = None       # path to service account JSON


@router.post("/api-keys")
def update_api_keys(request: ApiKeysRequest):
    """Set API keys at runtime — used by the Settings panel in the desktop app."""
    try:
        if request.gemini_api_key:
            secret_manager.set_override('GEMINI_API_KEY', request.gemini_api_key)
            # Reset cached service instances so next request picks up the new key
            transcription_controller._service = None
            insights_controller._service = None
            meeting_act_controller._service = None
        if request.monday_token:
            secret_manager.set_override('MONDAY_API_TOKEN', request.monday_token)
        if request.monday_board_id:
            secret_manager.set_override('MONDAY_BOARD_ID', request.monday_board_id)
        if request.monday_column_id:
            secret_manager.set_override('MONDAY_COLUMN_ID', request.monday_column_id)
        if request.transcription_mode:
            secret_manager.set_override('TRANSCRIPTION_MODE', request.transcription_mode)
            transcription_controller._service = None
        if request.whisper_model:
            secret_manager.set_override('WHISPER_MODEL', request.whisper_model)
            transcription_controller._service = None
        if request.vertex_sa_path is not None:
            secret_manager.set_override('VERTEX_SA_PATH', request.vertex_sa_path)
            insights_controller._service = None
            meeting_act_controller._service = None
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def settings_status():
    """Returns which keys are configured (without revealing values)."""
    def is_set(getter):
        try:
            getter()
            return True
        except RuntimeError:
            return False

    vertex_path = secret_manager.get_vertex_sa_path()
    vertex_project = None
    if vertex_path:
        try:
            import json
            with open(vertex_path) as f:
                vertex_project = json.load(f).get("project_id")
        except Exception:
            pass

    active_backend = "vertex_ai" if vertex_path else "ai_studio"

    return {
        "gemini_configured": is_set(secret_manager.get_gemini_api_key),
        "vertex_configured": bool(vertex_path),
        "vertex_project": vertex_project,
        "active_backend": active_backend,
        "monday_configured": is_set(secret_manager.get_monday_api_token),
        "monday_board_configured": is_set(secret_manager.get_monday_board_id),
        "monday_column_configured": is_set(secret_manager.get_monday_column_id),
    }
