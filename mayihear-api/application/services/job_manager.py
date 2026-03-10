import threading
import uuid
from typing import Any, Callable, Optional

_jobs: dict = {}
_lock = threading.Lock()


def create_job() -> str:
    job_id = str(uuid.uuid4())[:8]
    with _lock:
        _jobs[job_id] = {
            "status": "running",
            "chunks_done": 0,
            "total_chunks": 0,
            "text": None,
            "error": None,
        }
    return job_id


def update_job(job_id: str, **kwargs):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def run_in_background(fn: Callable, *args, **kwargs):
    t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t
