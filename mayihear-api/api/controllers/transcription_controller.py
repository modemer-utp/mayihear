import os

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from application.services import job_manager
from application.services.transcription_service import TranscriptionService
from domain.models.output.transcript_result import TranscriptResult

router = APIRouter(prefix="/transcription", tags=["transcription"])
service = TranscriptionService()


@router.post("/transcribe", response_model=TranscriptResult)
async def transcribe(file: UploadFile = File(...)):
    return service.transcribe(file)


class TranscribeFileRequest(BaseModel):
    file_path: str


@router.post("/transcribe-file")
async def transcribe_file(request: TranscribeFileRequest):
    """Kicks off a background transcription job. Returns job_id immediately."""
    if not os.path.exists(request.file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {request.file_path}")
    job_id = service.start_transcribe_job(request.file_path)
    return {"job_id": job_id}


@router.get("/status/{job_id}")
async def transcribe_status(job_id: str):
    """Poll the status of a transcription job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job
