from typing import TypedDict
from domain.models.output.meeting_act_result import MeetingActResult


class MeetingActState(TypedDict):
    transcript: str
    user_context: str
    today_date: str


class MeetingActOutputState(TypedDict):
    meeting_act_result: MeetingActResult
