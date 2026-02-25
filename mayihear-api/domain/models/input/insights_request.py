from pydantic import BaseModel


class InsightsRequest(BaseModel):
    transcript: str
    user_context: str = ""
