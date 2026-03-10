"""
Transcribes a saved recording by sending it directly to the local API (chunked, background job).
Run from the project root: python transcribe_recording.py
"""
import requests
import os
import sys
import time

RECORDING = r"D:\Proyectos actuales\mayihear-utp\recording.webm"
OUTPUT    = r"D:\Proyectos actuales\mayihear-utp\recordings\transcripcion_2026-03-09.txt"
API_BASE  = "http://localhost:8001"


def main():
    if not os.path.exists(RECORDING):
        print(f"ERROR: No se encontro el archivo: {RECORDING}")
        sys.exit(1)

    size_mb = os.path.getsize(RECORDING) / 1024 / 1024
    print(f"Archivo: {RECORDING}")
    print(f"Tamano:  {size_mb:.1f} MB")
    print(f"Iniciando transcripcion por fragmentos...")
    print()

    # Start background job
    response = requests.post(
        f"{API_BASE}/transcription/transcribe-file",
        json={"file_path": RECORDING},
        timeout=30
    )
    if response.status_code != 200:
        print(f"ERROR {response.status_code}: {response.text}")
        sys.exit(1)

    job_id = response.json()["job_id"]
    print(f"Job iniciado: {job_id}")
    print("Esperando resultados (polling cada 10s)...")
    print()

    # Poll until done
    while True:
        time.sleep(10)
        try:
            status_resp = requests.get(f"{API_BASE}/transcription/status/{job_id}", timeout=10)
        except Exception as e:
            print(f"  Poll error: {e} — reintentando...")
            continue

        if status_resp.status_code != 200:
            print(f"  Poll error {status_resp.status_code} — reintentando...")
            continue

        status = status_resp.json()
        job_status = status.get("status")
        chunks_done = status.get("chunks_done", 0)
        total_chunks = status.get("total_chunks", 0)

        if total_chunks > 0:
            print(f"  Fragmento {chunks_done}/{total_chunks} completado...")
        else:
            print(f"  Procesando... ({job_status})")

        if job_status == "done":
            break
        if job_status == "error":
            print(f"ERROR: {status.get('error', 'Error desconocido')}")
            sys.exit(1)

    transcript = status.get("text", "").strip()
    if not transcript:
        print("ERROR: La transcripcion esta vacia.")
        sys.exit(1)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(transcript)

    print()
    print(f"Transcripcion completada!")
    print(f"Guardada en: {OUTPUT}")
    print(f"Caracteres:  {len(transcript)}")


if __name__ == "__main__":
    main()
