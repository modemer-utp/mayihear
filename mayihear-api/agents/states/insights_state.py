from typing import TypedDict
from domain.models.output.insights_result import InsightsResult


class InsightsState(TypedDict):
    transcript: str
    user_context: str


class InsightsOutputState(TypedDict):
    insights_result: InsightsResult
