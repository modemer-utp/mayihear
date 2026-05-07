import os
import re
import subprocess
import tempfile
import time
from typing import Callable, List, Optional

from google import genai
from google.genai import errors as genai_errors

from application.utilities.pricing import compute_cost
from domain.models.output.token_usage import TokenUsage
from domain.models.output.transcript_result import TranscriptResult
from infrastructure.utilities import secret_manager

CHUNK_MINUTES = 30
CHUNK_SECONDS = CHUNK_MINUTES * 60

TRANSCRIPTION_MODEL = "gemini-2.5-pro"
TRANSCRIPTION_MODEL_FALLBACK = "gemini-2.5-flash-lite"

_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 5

TRANSCRIPTION_PROMPT = (
    "Transcribe this audio recording accurately. "
    "If multiple speakers are present, label them as Speaker 1, Speaker 2, etc. "
    "Return only the transcription text, no explanations or extra formatting."
)


def _get_ffmpeg_path() -> str:
    """Returns path to bundled ffmpeg, or falls back to system ffmpeg."""
    import sys
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
    bundled = os.path.join(base, 'bin', 'ffmpeg.exe')
    print(f"[ffmpeg] bundled path = '{bundled}' | exists = {os.path.exists(bundled)}", flush=True)
    if os.path.exists(bundled):
        return bundled
    # Try to locate ffmpeg in PATH explicitly
    import shutil
    system_ffmpeg = shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')
    print(f"[ffmpeg] system path = '{system_ffmpeg}'", flush=True)
    return system_ffmpeg or 'ffmpeg'


def _split_into_chunks(file_path: str, chunk_seconds: int) -> List[str]:
    """Split audio into chunks using ffmpeg segment muxer. Returns list of temp file paths."""
    ffmpeg = _get_ffmpeg_path()
    ext = os.path.splitext(file_path)[1] or '.webm'

    tmp_dir = tempfile.mkdtemp()
    pattern = os.path.join(tmp_dir, f'chunk_%03d{ext}')

    print(f"[chunker] Splitting into {chunk_seconds // 60}-min chunks, file='{file_path}', ffmpeg='{ffmpeg}'", flush=True)
    result = subprocess.run([
        ffmpeg, '-y', '-i', file_path,
        '-f', 'segment',
        '-segment_time', str(chunk_seconds),
        '-c', 'copy',
        '-reset_timestamps', '1',
        pattern
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # Collect produced chunk files in order
    chunks = sorted([
        os.path.join(tmp_dir, f)
        for f in os.listdir(tmp_dir)
        if f.startswith('chunk_') and f.endswith(ext)
    ])

    if not chunks:
        # ffmpeg couldn't segment — fall back to single chunk
        stderr_text = result.stderr.decode('utf-8', errors='replace')
        print(f"[chunker] Segment failed, using original file. ffmpeg: {stderr_text[:200]}", flush=True)
        return [file_path]

    print(f"[chunker] Created {len(chunks)} chunk(s)", flush=True)
    return chunks


def _transcribe_one_chunk(client, chunk_path: str, mime_type: str, chunk_idx: int, total: int) -> tuple:
    """Upload and transcribe a single audio chunk. Returns (text, model_used, usage_metadata)."""
    from google.genai import types as genai_types
    file_size_mb = round(os.path.getsize(chunk_path) / 1024 / 1024, 1)
    print(f"[chunker] Chunk {chunk_idx + 1}/{total}: preparing {file_size_mb} MB...", flush=True)

    is_vertex = bool(secret_manager.get_vertex_sa_path())

    if is_vertex:
        # Vertex AI: send audio inline as bytes
        with open(chunk_path, 'rb') as f:
            audio_bytes = f.read()
        audio_part = genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        audio_content = audio_part
        audio_file = None
    else:
        # AI Studio: upload file then reference it
        audio_file = client.files.upload(file=chunk_path, config={"mime_type": mime_type})
        while audio_file.state.name == "PROCESSING":
            time.sleep(1)
            audio_file = client.files.get(name=audio_file.name)
        if audio_file.state.name == "FAILED":
            raise RuntimeError(f"Gemini failed to process chunk {chunk_idx + 1}/{total}")
        audio_content = audio_file

    print(f"[chunker] Chunk {chunk_idx + 1}/{total}: transcribing...", flush=True)

    response = None
    model_used = TRANSCRIPTION_MODEL

    for model in [TRANSCRIPTION_MODEL, TRANSCRIPTION_MODEL_FALLBACK]:
        for attempt in range(_MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[TRANSCRIPTION_PROMPT, audio_content]
                )
                model_used = model
                break
            except (genai_errors.ServerError, genai_errors.ClientError) as e:
                retryable = getattr(e, 'code', 0) in (429, 503)
                if retryable and attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                if model == TRANSCRIPTION_MODEL:
                    break
                raise
        if response:
            break

    if audio_file:
        client.files.delete(name=audio_file.name)

    if not response:
        raise RuntimeError(f"Transcription unavailable for chunk {chunk_idx + 1}/{total} after all retries")

    text = response.text or ''
    print(f"[chunker] Chunk {chunk_idx + 1}/{total}: done ({len(text)} chars)", flush=True)
    return text, model_used, response.usage_metadata


def transcribe_chunked(
    file_path: str,
    mime_type: str,
    on_progress: Optional[Callable[[int, int], None]] = None
) -> TranscriptResult:
    """
    Splits audio into 30-min chunks, transcribes each with gemini-2.5-pro, concatenates results.
    on_progress(chunks_done, total_chunks) called after each chunk completes.
    """
    creds, project_id = secret_manager.get_vertex_credentials()
    if creds:
        client = genai.Client(vertexai=True, project=project_id, location="us-central1", credentials=creds)
    else:
        client = genai.Client(api_key=secret_manager.get_gemini_api_key())
    start_total = time.perf_counter()

    chunks = _split_into_chunks(file_path, CHUNK_SECONDS)
    total = len(chunks)
    created_temp_files = chunks != [file_path]

    texts: List[str] = []
    total_input_tokens = 0
    total_output_tokens = 0
    last_model_used = TRANSCRIPTION_MODEL

    try:
        for i, chunk_path in enumerate(chunks):
            text, model_used, meta = _transcribe_one_chunk(client, chunk_path, mime_type, i, total)
            texts.append(text.strip())
            last_model_used = model_used
            total_input_tokens += meta.prompt_token_count or 0
            total_output_tokens += meta.candidates_token_count or 0

            if on_progress:
                on_progress(i + 1, total)
    finally:
        if created_temp_files:
            import shutil
            chunk_dir = os.path.dirname(chunks[0])
            try:
                shutil.rmtree(chunk_dir, ignore_errors=True)
            except Exception:
                pass

    full_text = '\n\n'.join(texts)
    processing_time = round(time.perf_counter() - start_total, 2)
    print(f"[chunker] All {total} chunk(s) done in {processing_time}s using {last_model_used}", flush=True)

    usage = TokenUsage(
        model=last_model_used,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        total_tokens=total_input_tokens + total_output_tokens,
        estimated_cost_usd=compute_cost(last_model_used, total_input_tokens, total_output_tokens, audio_input=True)
    )
    recording_duration = round(total_input_tokens / 32, 1)

    return TranscriptResult(
        text=full_text,
        usage=usage,
        recording_duration_seconds=recording_duration,
        processing_time_seconds=processing_time,
    )
