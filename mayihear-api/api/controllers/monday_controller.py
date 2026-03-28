from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from application.services.monday_service import MondayService
from domain.models.input.monday_publish_request import MondayPublishRequest
from domain.models.output.monday_result import BoardInfo, ItemInfo, ColumnInfo, BoardDetails, MondayPublishResult

router = APIRouter(prefix="/monday", tags=["monday"])
service = MondayService()


@router.get("/boards", response_model=List[BoardInfo])
def list_boards():
    try:
        return service.list_boards()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/boards/{board_id}/items", response_model=List[ItemInfo])
def list_items(board_id: str):
    try:
        return service.list_items(board_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/boards/{board_id}/columns", response_model=List[ColumnInfo])
def list_columns(board_id: str):
    try:
        return service.list_columns(board_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects", response_model=List[ItemInfo])
def list_projects():
    try:
        return service.list_projects()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/boards/{board_id}/details", response_model=BoardDetails)
def board_details(board_id: str):
    try:
        return service.get_board_details(board_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UpdateMondaySettingsRequest(BaseModel):
    token: str
    board_id: Optional[str] = None
    column_id: Optional[str] = None


@router.post("/settings")
def update_monday_settings(request: UpdateMondaySettingsRequest):
    try:
        service.update_monday_settings(request.token, request.board_id, request.column_id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PublishActaRequest(BaseModel):
    item_id: str
    content: str


@router.post("/publish-acta", response_model=MondayPublishResult)
def publish_acta(request: PublishActaRequest):
    result = service.publish_acta(request.item_id, request.content)
    if not result.ok:
        raise HTTPException(status_code=500, detail=result.error)
    return result


@router.post("/publish", response_model=MondayPublishResult)
def publish(request: MondayPublishRequest):
    result = service.publish(request)
    if not result.ok:
        raise HTTPException(status_code=500, detail=result.error)
    return result
