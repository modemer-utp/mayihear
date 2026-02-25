from application.handlers.generate_insights import GenerateInsights
from domain.models.input.insights_request import InsightsRequest
from domain.models.output.insights_result import InsightsResult


class InsightsService:

    def __init__(self):
        self.handler = GenerateInsights()

    def generate(self, request: InsightsRequest) -> InsightsResult:
        return self.handler.execute(request)
