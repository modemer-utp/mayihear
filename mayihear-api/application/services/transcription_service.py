from fastapi import UploadFile

from application.handlers.transcribe_audio import TranscribeAudio
from domain.models.output.transcript_result import TranscriptResult


class TranscriptionService:

    def __init__(self):
        self.handler = TranscribeAudio()

    def transcribe(self, file: UploadFile) -> TranscriptResult:
        return self.handler.execute(file)
