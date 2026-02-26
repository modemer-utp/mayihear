import os
import time
import tempfile

from google import genai
from google.genai import errors as genai_errors
from fastapi import UploadFile

from domain.models.output.transcript_result import TranscriptResult
from domain.models.output.token_usage import TokenUsage
from infrastructure.utilities import secret_manager
from application.utilities.pricing import compute_cost

# gemini-2.5-pro: best accuracy, up to 9.5h audio, speaker diarization
# Falls back to gemini-2.0-flash if primary model is unavailable
TRANSCRIPTION_MODEL = "gemini-2.5-pro"
TRANSCRIPTION_MODEL_FALLBACK = "gemini-2.0-flash"

_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 5

TRANSCRIPTION_PROMPT = (
    "Transcribe this audio recording accurately. "
    "If multiple speakers are present, label them as Speaker 1, Speaker 2, etc. "
    "Return only the transcription text, no explanations or extra formatting."
)


class TranscribeAudio:

    def __init__(self):
        self.client = genai.Client(api_key=secret_manager.get_gemini_api_key())

    def _generate_with_retry(self, audio_file) -> tuple:
        """Calls generate_content with retry on 503/429 and falls back to a stable model.
        Returns (response, model_name) tuple."""
        for model in [TRANSCRIPTION_MODEL, TRANSCRIPTION_MODEL_FALLBACK]:
            for attempt in range(_MAX_RETRIES):
                try:
                    response = self.client.models.generate_content(
                        model=model,
                        contents=[TRANSCRIPTION_PROMPT, audio_file]
                    )
                    return response, model
                except genai_errors.ServerError as e:
                    retryable = e.status_code in (503, 429)
                    if retryable and (attempt < _MAX_RETRIES - 1 or model == TRANSCRIPTION_MODEL):
                        wait = _RETRY_DELAY_SECONDS * (attempt + 1)
                        time.sleep(wait)
                        continue
                    if model == TRANSCRIPTION_MODEL:
                        break  # Try fallback model
                    raise
        raise RuntimeError("Gemini transcription unavailable after retries on all models.")

    def _extract_usage(self, response, model: str) -> TokenUsage:
        meta = response.usage_metadata
        input_tokens = meta.prompt_token_count or 0
        output_tokens = meta.candidates_token_count or 0
        return TokenUsage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            estimated_cost_usd=compute_cost(model, input_tokens, output_tokens, audio_input=True)
        )

    def execute(self, file: UploadFile) -> TranscriptResult:
        suffix = os.path.splitext(file.filename)[1] if file.filename else ".webm"
        mime_type = file.content_type or "audio/webm"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name

        try:
            start = time.perf_counter()

            # Upload audio to Gemini File API (handles large files)
            audio_file = self.client.files.upload(
                file=tmp_path,
                config={"mime_type": mime_type}
            )

            # Wait until Gemini finishes processing the uploaded file
            while audio_file.state.name == "PROCESSING":
                time.sleep(1)
                audio_file = self.client.files.get(name=audio_file.name)

            if audio_file.state.name == "FAILED":
                raise RuntimeError("Gemini failed to process the audio file.")

            response, model_used = self._generate_with_retry(audio_file)
            processing_time = round(time.perf_counter() - start, 2)

            # Clean up uploaded file from Gemini
            self.client.files.delete(name=audio_file.name)

            usage = self._extract_usage(response, model_used)
            # Gemini tokenizes audio at ~32 tokens/second
            recording_duration = round(usage.input_tokens / 32, 1)

            return TranscriptResult(
                text=response.text.strip(),
                usage=usage,
                recording_duration_seconds=recording_duration,
                processing_time_seconds=processing_time,
            )

        finally:
            os.unlink(tmp_path)
