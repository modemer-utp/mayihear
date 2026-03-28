from fastapi import APIRouter

from application.services.insights_service import InsightsService
from domain.models.input.insights_request import InsightsRequest
from domain.models.output.insights_result import InsightsResult

router = APIRouter(prefix="/insights", tags=["insights"])
_service = None

def get_service() -> InsightsService:
    global _service
    if _service is None:
        _service = InsightsService()
    return _service


@router.post("/generate", response_model=InsightsResult)
async def generate_insights(request: InsightsRequest):
    return get_service().generate(request)
