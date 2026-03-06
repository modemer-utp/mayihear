from pydantic import BaseModel
from typing import Optional


class MondayPublishRequest(BaseModel):
    board_id: str
    item_id: str
    column_id: Optional[str] = None  # None = post as update (comment)
    content: str
