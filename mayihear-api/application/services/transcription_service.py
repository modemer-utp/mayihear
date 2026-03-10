import os

from fastapi import UploadFile

from application.handlers.chunk_transcriber import transcribe_chunked
from application.handlers.transcribe_audio import TranscribeAudio
from application.services import job_manager
from domain.models.output.transcript_result import TranscriptResult
from infrastructure.utilities import usage_logger


class TranscriptionService:

    def __init__(self):
        self.handler = TranscribeAudio()

    def transcribe(self, file: UploadFile) -> TranscriptResult:
        result = self.handler.execute(file)
        if result.usage:
            usage_logger.log(
                result.usage,
                "transcription",
                processing_time_seconds=result.processing_time_seconds,
                recording_duration_seconds=result.recording_duration_seconds,
            )
        return result

    def start_transcribe_job(self, file_path: str) -> str:
        """Creates a background job for chunked transcription. Returns job_id."""
        job_id = job_manager.create_job()
        job_manager.run_in_background(self._run_transcribe_job, job_id, file_path)
        return job_id

    def _run_transcribe_job(self, job_id: str, file_path: str):
        try:
            ext = os.path.splitext(file_path)[1].lower()
            mime_map = {
                ".webm": "audio/webm",
                ".wav": "audio/wav",
                ".mp3": "audio/mpeg",
                ".mp4": "audio/mp4",
                ".m4a": "audio/mp4",
            }
            mime_type = mime_map.get(ext, "audio/webm")

            def on_progress(chunks_done: int, total_chunks: int):
                job_manager.update_job(job_id, chunks_done=chunks_done, total_chunks=total_chunks)

            result = transcribe_chunked(file_path, mime_type, on_progress=on_progress)

            if result.usage:
                usage_logger.log(
                    result.usage,
                    "transcription",
                    processing_time_seconds=result.processing_time_seconds,
                    recording_duration_seconds=result.recording_duration_seconds,
                )

            job_manager.update_job(
                job_id,
                status="done",
                text=result.text,
                chunks_done=job_manager.get_job(job_id)["total_chunks"],
            )

        except Exception as e:
            print(f"[job:{job_id}] ERROR: {e}", flush=True)
            job_manager.update_job(job_id, status="error", error=str(e))
