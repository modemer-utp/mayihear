from pydantic import BaseModel
from typing import List, Optional


class ActionItem(BaseModel):
    person: Optional[str] = None
    task: str


class InsightsResult(BaseModel):
    summary: List[str]
    decisions: List[str]
    action_items: List[ActionItem]
    open_questions: List[str]
