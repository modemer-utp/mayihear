from agents.insights_agent import InsightsAgent
from domain.models.input.insights_request import InsightsRequest
from domain.models.output.insights_result import InsightsResult


class GenerateInsights:

    def __init__(self):
        self.agent = InsightsAgent()

    def execute(self, request: InsightsRequest) -> InsightsResult:
        return self.agent.invoke(
            transcript=request.transcript,
            user_context=request.user_context
        )
