import os
import threading
import uuid
from typing import Callable, Optional

from infrastructure.database import upsert_job, get_job as db_get_job, list_jobs as db_list_jobs


def create_job(file_path: str = None, profile_id: str = None) -> str:
    job_id = str(uuid.uuid4())[:8]
    file_name = os.path.basename(file_path) if file_path else None
    fields = dict(
        status='running',
        file_path=file_path,
        file_name=file_name,
        chunks_done=0,
        total_chunks=0,
    )
    if profile_id:
        fields['profile_id'] = profile_id
    upsert_job(job_id, **fields)
    return job_id


def update_job(job_id: str, **kwargs):
    upsert_job(job_id, **kwargs)


def get_job(job_id: str) -> Optional[dict]:
    return db_get_job(job_id)


def list_jobs() -> list:
    return db_list_jobs()


def run_in_background(fn: Callable, *args, **kwargs):
    t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t
