from typing import Optional
from pydantic import BaseModel

from domain.models.output.token_usage import TokenUsage


class TranscriptResult(BaseModel):
    text: str
    usage: Optional[TokenUsage] = None
    recording_duration_seconds: Optional[float] = None
    processing_time_seconds: Optional[float] = None
