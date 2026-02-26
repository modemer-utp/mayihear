from application.handlers.generate_insights import GenerateInsights
from domain.models.input.insights_request import InsightsRequest
from domain.models.output.insights_result import InsightsResult
from infrastructure.utilities import usage_logger


class InsightsService:

    def __init__(self):
        self.handler = GenerateInsights()

    def generate(self, request: InsightsRequest) -> InsightsResult:
        result = self.handler.execute(request)
        if result.usage:
            usage_logger.log(
                result.usage,
                "insights",
                processing_time_seconds=result.processing_time_seconds,
            )
        return result
