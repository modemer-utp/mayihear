from pydantic import BaseModel


class MeetingActRequest(BaseModel):
    transcript: str
    user_context: str = ""
    acta_template: str = ""
