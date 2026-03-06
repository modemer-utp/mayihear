from fastapi import APIRouter, HTTPException
from typing import List

from application.services.monday_service import MondayService
from domain.models.input.monday_publish_request import MondayPublishRequest
from domain.models.output.monday_result import BoardInfo, ItemInfo, ColumnInfo, MondayPublishResult

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


@router.post("/publish", response_model=MondayPublishResult)
def publish(request: MondayPublishRequest):
    result = service.publish(request)
    if not result.ok:
        raise HTTPException(status_code=500, detail=result.error)
    return result
