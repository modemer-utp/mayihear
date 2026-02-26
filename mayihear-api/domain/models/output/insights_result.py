from pydantic import BaseModel
from typing import List, Optional

from domain.models.output.token_usage import TokenUsage


class ActionItem(BaseModel):
    person: Optional[str] = None
    task: str


class InsightsResult(BaseModel):
    summary: List[str]
    decisions: List[str]
    action_items: List[ActionItem]
    open_questions: List[str]
    usage: Optional[TokenUsage] = None
    processing_time_seconds: Optional[float] = None
