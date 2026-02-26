from application.handlers.generate_meeting_act import GenerateMeetingAct
from domain.models.input.meeting_act_request import MeetingActRequest
from domain.models.output.meeting_act_result import MeetingActResult
from infrastructure.utilities import usage_logger


class MeetingActService:

    def __init__(self):
        self.handler = GenerateMeetingAct()

    def generate(self, request: MeetingActRequest) -> MeetingActResult:
        result = self.handler.execute(request)
        if result.usage:
            usage_logger.log(
                result.usage,
                "meeting_act",
                processing_time_seconds=result.processing_time_seconds,
            )
        return result
