"""SQLite persistence for jobs and settings."""
import os
import sqlite3
import threading
from typing import Optional

_lock = threading.Lock()


def _get_db_path() -> str:
    data_dir = os.environ.get('MAYIHEAR_DATA_DIR') or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'
    )
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'mayihear.db')


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = _connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'running',
                file_path TEXT,
                file_name TEXT,
                chunks_done INTEGER DEFAULT 0,
                total_chunks INTEGER DEFAULT 0,
                text TEXT,
                insights_text TEXT,
                profile_id TEXT,
                error TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                track TEXT,
                context_for_insights TEXT,
                acta_template TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
        """)
        # Migrate: add columns if not present
        cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
        if 'insights_text' not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN insights_text TEXT")
        if 'profile_id' not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN profile_id TEXT")
        # Mark interrupted jobs as error (API restart scenario)
        conn.execute(
            "UPDATE jobs SET status='error', error='Interrumpido: API reiniciada' WHERE status='running'"
        )
        conn.commit()
        conn.close()
    print("[DB] SQLite initialized", flush=True)


def upsert_job(job_id: str, **fields):
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row:
            parts = [f"{k}=?" for k in fields]
            parts.append("updated_at=datetime('now', 'localtime')")
            conn.execute(
                f"UPDATE jobs SET {', '.join(parts)} WHERE id=?",
                [*fields.values(), job_id]
            )
        else:
            all_fields = {'id': job_id, **fields}
            cols = ', '.join(all_fields)
            phs = ', '.join('?' for _ in all_fields)
            conn.execute(f"INSERT INTO jobs ({cols}) VALUES ({phs})", list(all_fields.values()))
        conn.commit()
        conn.close()


def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.close()
        return dict(row) if row else None


def list_jobs() -> list:
    with _lock:
        conn = _connect()
        rows = conn.execute(
            """SELECT id, status, file_name, chunks_done, total_chunks, error,
                      created_at, updated_at, profile_id
               FROM jobs ORDER BY created_at DESC LIMIT 50"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_job_text(job_id: str) -> Optional[str]:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT text FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.close()
        return row['text'] if row else None


def save_job_insights(job_id: str, insights_text: str):
    with _lock:
        conn = _connect()
        conn.execute(
            "UPDATE jobs SET insights_text=?, updated_at=datetime('now','localtime') WHERE id=?",
            (insights_text, job_id)
        )
        conn.commit()
        conn.close()


def get_job_insights(job_id: str) -> Optional[str]:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT insights_text FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.close()
        return row['insights_text'] if row else None


# ── Profile CRUD ──────────────────────────────────────────────────────────────

def create_profile(profile_id: str, name: str, track: str = '', context_for_insights: str = '', acta_template: str = ''):
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO profiles (id, name, track, context_for_insights, acta_template) VALUES (?,?,?,?,?)",
            (profile_id, name, track, context_for_insights, acta_template)
        )
        conn.commit()
        conn.close()


def update_profile(profile_id: str, name: str, track: str = '', context_for_insights: str = '', acta_template: str = ''):
    with _lock:
        conn = _connect()
        conn.execute(
            """UPDATE profiles SET name=?, track=?, context_for_insights=?, acta_template=?,
               updated_at=datetime('now','localtime') WHERE id=?""",
            (name, track, context_for_insights, acta_template, profile_id)
        )
        conn.commit()
        conn.close()


def delete_profile(profile_id: str):
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        conn.commit()
        conn.close()


def get_profile_by_id(profile_id: str) -> Optional[dict]:
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        conn.close()
        return dict(row) if row else None


def list_profiles() -> list:
    with _lock:
        conn = _connect()
        rows = conn.execute("SELECT * FROM profiles ORDER BY created_at ASC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
