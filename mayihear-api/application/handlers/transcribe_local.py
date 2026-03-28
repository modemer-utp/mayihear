import os
import subprocess
import tempfile
import time

from fastapi import UploadFile

from domain.models.output.transcript_result import TranscriptResult

WHISPER_MODEL_DEFAULT = "small"

# Cache loaded models so re-use across requests is fast
_model_cache: dict = {}


def _get_ffmpeg_path() -> str:
    bundled = os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'bin', 'ffmpeg.exe')
    )
    if os.path.exists(bundled):
        return bundled
    return 'ffmpeg'


def _get_model(model_name: str):
    if model_name not in _model_cache:
        from faster_whisper import WhisperModel
        print(f"[whisper-local] Loading model '{model_name}' (may download ~244MB on first run)...", flush=True)
        _model_cache[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
        print(f"[whisper-local] Model '{model_name}' ready.", flush=True)
    return _model_cache[model_name]


def _to_wav(input_path: str) -> str:
    """Convert any audio file to 16kHz mono WAV for Whisper. Returns temp wav path."""
    ffmpeg = _get_ffmpeg_path()
    tmp_wav = tempfile.mktemp(suffix='.wav')
    subprocess.run(
        [ffmpeg, '-y', '-i', input_path, '-ar', '16000', '-ac', '1', '-f', 'wav', tmp_wav],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
    )
    return tmp_wav


class TranscribeAudioLocal:

    def __init__(self, model_name: str = WHISPER_MODEL_DEFAULT):
        self.model_name = model_name

    def execute_from_path(self, file_path: str) -> TranscriptResult:
        start = time.perf_counter()
        wav_path = None
        try:
            print(f"[whisper-local] Converting audio to WAV...", flush=True)
            wav_path = _to_wav(file_path)

            model = _get_model(self.model_name)
            print(f"[whisper-local] Transcribing with '{self.model_name}'...", flush=True)

            segments, info = model.transcribe(wav_path, beam_size=5, vad_filter=True)
            text = ' '.join(seg.text.strip() for seg in segments)

            processing_time = round(time.perf_counter() - start, 2)
            print(
                f"[whisper-local] Done in {processing_time}s — "
                f"language: {info.language} ({info.language_probability:.2f})",
                flush=True
            )
            return TranscriptResult(text=text, processing_time_seconds=processing_time)
        finally:
            if wav_path and os.path.exists(wav_path):
                os.unlink(wav_path)

    def execute(self, file: UploadFile) -> TranscriptResult:
        suffix = os.path.splitext(file.filename)[1] if file.filename else '.webm'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name
        try:
            return self.execute_from_path(tmp_path)
        finally:
            os.unlink(tmp_path)
