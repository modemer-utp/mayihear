from pydantic import BaseModel
from typing import Optional


class BoardInfo(BaseModel):
    id: str
    name: str


class ItemInfo(BaseModel):
    id: str
    name: str


class ColumnInfo(BaseModel):
    id: str
    title: str
    type: str


class MondayPublishResult(BaseModel):
    ok: bool
    update_id: Optional[str] = None
    error: Optional[str] = None
