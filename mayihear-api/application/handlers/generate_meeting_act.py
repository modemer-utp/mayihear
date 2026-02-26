import time

from agents.meeting_act_agent import MeetingActAgent
from domain.models.input.meeting_act_request import MeetingActRequest
from domain.models.output.meeting_act_result import MeetingActResult


class GenerateMeetingAct:

    def __init__(self):
        self.agent = MeetingActAgent()

    def execute(self, request: MeetingActRequest) -> MeetingActResult:
        start = time.perf_counter()
        result = self.agent.invoke(
            transcript=request.transcript,
            user_context=request.user_context
        )
        processing_time = round(time.perf_counter() - start, 2)
        return result.model_copy(update={"processing_time_seconds": processing_time})
