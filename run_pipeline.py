"""
Full pipeline for a saved recording:
  1. Transcribe (chunked background job)
  2. Generate insights
  3. Generate meeting acta (JSON)
  4. Generate Word .docx
Run: python run_pipeline.py
"""
import json
import os
import sys
import time
import requests

RECORDING   = r"D:\Proyectos actuales\mayihear-utp\recordings\recording_2026-03-13T18-06-22.webm"
OUT_DIR     = r"D:\Proyectos actuales\mayihear-utp\recordings"
BASE_NAME   = "2026-03-13"
API_BASE    = "http://localhost:8001"

TRANSCRIPT_FILE = os.path.join(OUT_DIR, f"transcripcion_{BASE_NAME}.txt")
INSIGHTS_FILE   = os.path.join(OUT_DIR, f"insights_{BASE_NAME}.json")
ACTA_FILE       = os.path.join(OUT_DIR, f"acta_{BASE_NAME}.docx")

# ── 1. Transcription ────────────────────────────────────────────────────────

def step_transcribe() -> str:
    if os.path.exists(TRANSCRIPT_FILE):
        print(f"[1/3] Transcripcion ya existe: {TRANSCRIPT_FILE}")
        with open(TRANSCRIPT_FILE, encoding="utf-8") as f:
            return f.read()

    size_mb = os.path.getsize(RECORDING) / 1024 / 1024
    print(f"[1/3] Iniciando transcripcion — {size_mb:.1f} MB")

    resp = requests.post(
        f"{API_BASE}/transcription/transcribe-file",
        json={"file_path": RECORDING},
        timeout=30,
    )
    resp.raise_for_status()
    job_id = resp.json()["job_id"]
    print(f"      Job: {job_id}  (polling cada 15s...)")

    while True:
        time.sleep(15)
        try:
            s = requests.get(f"{API_BASE}/transcription/status/{job_id}", timeout=10).json()
        except Exception as e:
            print(f"      Poll error: {e} — reintentando...")
            continue

        status = s.get("status")
        done   = s.get("chunks_done", 0)
        total  = s.get("total_chunks", 0)
        if total:
            print(f"      Fragmento {done}/{total} — {status}")
        else:
            print(f"      {status}...")

        if status == "done":
            break
        if status == "error":
            print(f"ERROR transcripcion: {s.get('error')}")
            sys.exit(1)

    text = s.get("text", "").strip()
    if not text:
        print("ERROR: transcripcion vacia")
        sys.exit(1)

    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"      Guardado: {TRANSCRIPT_FILE}  ({len(text):,} chars)")
    return text


# ── 2. Insights ─────────────────────────────────────────────────────────────

def step_insights(transcript: str) -> dict:
    if os.path.exists(INSIGHTS_FILE):
        print(f"[2/3] Insights ya existen: {INSIGHTS_FILE}")
        with open(INSIGHTS_FILE, encoding="utf-8") as f:
            return json.load(f)

    print("[2/3] Generando insights...")
    resp = requests.post(
        f"{API_BASE}/insights/generate",
        json={"transcript": transcript},
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()

    with open(INSIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"      Guardado: {INSIGHTS_FILE}")
    return data


# ── 3. Meeting acta (Word) ───────────────────────────────────────────────────

def step_acta(transcript: str):
    if os.path.exists(ACTA_FILE):
        print(f"[3/3] Acta ya existe: {ACTA_FILE}")
        return

    print("[3/3] Generando acta...")
    # First get the structured acta JSON
    resp = requests.post(
        f"{API_BASE}/meeting-act/generate",
        json={"transcript": transcript},
        timeout=300,
    )
    resp.raise_for_status()
    acta_data = resp.json()

    # Then convert to Word
    word_resp = requests.post(
        f"{API_BASE}/meeting-act/word",
        json=acta_data,
        timeout=60,
    )
    word_resp.raise_for_status()

    with open(ACTA_FILE, "wb") as f:
        f.write(word_resp.content)
    print(f"      Guardado: {ACTA_FILE}")
    return acta_data


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(RECORDING):
        print(f"ERROR: No se encontro el archivo: {RECORDING}")
        sys.exit(1)

    transcript = step_transcribe()
    insights   = step_insights(transcript)
    step_acta(transcript)

    print()
    print("=" * 60)
    print("PIPELINE COMPLETO")
    print("=" * 60)
    print(f"Transcripcion : {TRANSCRIPT_FILE}")
    print(f"Insights      : {INSIGHTS_FILE}")
    print(f"Acta Word     : {ACTA_FILE}")
    print()
    print("── INSIGHTS ──────────────────────────────────────────────")
    for b in insights.get("summary", []):
        print(f"  • {b}")
    print()
    items = insights.get("action_items", [])
    if items:
        print("── ACTION ITEMS ──────────────────────────────────────────")
        for ai in items:
            print(f"  [{ai.get('person','')}] {ai.get('task','')}")


if __name__ == "__main__":
    main()
