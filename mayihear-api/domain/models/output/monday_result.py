from pydantic import BaseModel
from typing import Optional, List


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


class GroupInfo(BaseModel):
    id: str
    title: str
    color: Optional[str] = None


class BoardDetails(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    items_count: Optional[int] = None
    groups: List[GroupInfo] = []
    columns: List[ColumnInfo] = []


class MondayPublishResult(BaseModel):
    ok: bool
    update_id: Optional[str] = None
    error: Optional[str] = None
