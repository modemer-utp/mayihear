from fastapi import APIRouter, File, UploadFile

from application.services.transcription_service import TranscriptionService
from domain.models.output.transcript_result import TranscriptResult

router = APIRouter(prefix="/transcription", tags=["transcription"])
service = TranscriptionService()


@router.post("/transcribe", response_model=TranscriptResult)
async def transcribe(file: UploadFile = File(...)):
    return service.transcribe(file)
