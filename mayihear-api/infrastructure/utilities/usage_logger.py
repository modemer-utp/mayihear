import json
import os
import uuid
from datetime import datetime
from typing import Literal, Optional

from domain.models.output.token_usage import TokenUsage

# In packaged builds, MAYIHEAR_DATA_DIR is set to app.getPath('userData') by Electron.
# In dev, falls back to mayihear-api/data/usage_log.json.
_DATA_DIR = os.environ.get(
    'MAYIHEAR_DATA_DIR',
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
)
_LOG_PATH = os.path.join(_DATA_DIR, "usage_log.json")


def _load() -> list:
    if not os.path.exists(_LOG_PATH):
        return []
    with open(_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(records: list) -> None:
    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
    with open(_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def log(
    usage: TokenUsage,
    entry_type: Literal["transcription", "insights", "meeting_act"],
    processing_time_seconds: Optional[float] = None,
    recording_duration_seconds: Optional[float] = None,
) -> None:
    records = _load()
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(),
        "type": entry_type,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "estimated_cost_usd": usage.estimated_cost_usd,
        "processing_time_seconds": processing_time_seconds,
    }
    if entry_type == "transcription":
        record["recording_duration_seconds"] = recording_duration_seconds
    records.append(record)
    _save(records)


def read_all() -> dict:
    records = _load()
    total_cost = round(sum(r["estimated_cost_usd"] for r in records), 6)
    total_tokens = sum(r["total_tokens"] for r in records)
    transcription_cost = round(sum(r["estimated_cost_usd"] for r in records if r["type"] == "transcription"), 6)
    insights_cost = round(sum(r["estimated_cost_usd"] for r in records if r["type"] == "insights"), 6)
    return {
        "records": records,
        "totals": {
            "entries": len(records),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "transcription_cost_usd": transcription_cost,
            "insights_cost_usd": insights_cost,
        }
    }
