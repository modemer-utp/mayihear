from fastapi import UploadFile

from application.handlers.transcribe_audio import TranscribeAudio
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
