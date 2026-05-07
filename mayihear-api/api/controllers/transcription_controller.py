import os
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from application.services import job_manager
from application.services.transcription_service import TranscriptionService
from domain.models.output.transcript_result import TranscriptResult
from infrastructure.database import get_job_text

router = APIRouter(prefix="/transcription", tags=["transcription"])
_service = None


def get_service() -> TranscriptionService:
    global _service
    if _service is None:
        _service = TranscriptionService()
    return _service


@router.post("/transcribe", response_model=TranscriptResult)
async def transcribe(file: UploadFile = File(...)):
    return get_service().transcribe(file)


class TranscribeFileRequest(BaseModel):
    file_path: str
    profile_id: Optional[str] = None


@router.post("/transcribe-file")
async def transcribe_file(request: TranscribeFileRequest):
    """Kicks off a background transcription job. Returns job_id immediately."""
    if not os.path.exists(request.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")
    job_id = get_service().start_transcribe_job(request.file_path, profile_id=request.profile_id)
    return {"job_id": job_id}


@router.get("/status/{job_id}")
async def transcribe_status(job_id: str):
    """Poll the status of a transcription job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@router.get("/jobs")
async def list_transcription_jobs():
    """List all transcription jobs (last 50, from SQLite)."""
    return job_manager.list_jobs()


@router.get("/job-text/{job_id}")
async def get_job_transcript_text(job_id: str):
    """Get the full transcript text for a completed job."""
    text = get_job_text(job_id)
    if text is None:
        raise HTTPException(status_code=404, detail="Job not found or not completed")
    return {"text": text}
