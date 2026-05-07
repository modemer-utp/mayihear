from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from application.services.insights_service import InsightsService
from domain.models.input.insights_request import InsightsRequest
from domain.models.output.insights_result import InsightsResult
from infrastructure.database import save_job_insights, get_job_insights

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


class SaveInsightsRequest(BaseModel):
    job_id: str
    insights_text: str


@router.post("/save")
async def save_insights(req: SaveInsightsRequest):
    save_job_insights(req.job_id, req.insights_text)
    return {"ok": True}


@router.get("/stored/{job_id}")
async def get_stored_insights(job_id: str):
    text = get_job_insights(job_id)
    return {"text": text}
