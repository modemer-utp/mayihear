from pydantic import BaseModel


class TranscriptResult(BaseModel):
    text: str
