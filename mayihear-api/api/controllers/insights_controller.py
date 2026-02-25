from fastapi import APIRouter

from application.services.insights_service import InsightsService
from domain.models.input.insights_request import InsightsRequest
from domain.models.output.insights_result import InsightsResult

router = APIRouter(prefix="/insights", tags=["insights"])
service = InsightsService()


@router.post("/generate", response_model=InsightsResult)
async def generate_insights(request: InsightsRequest):
    return service.generate(request)
