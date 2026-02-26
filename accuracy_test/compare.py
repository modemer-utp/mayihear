"""
MayiHear — WER/CER Accuracy Comparison Script
==============================================
Compares a reference transcript (ground truth) against a MayiHear transcript
and reports Word Error Rate (WER), Character Error Rate (CER), and other metrics.

Usage:
    python compare.py --reference subtitles.txt --hypothesis mayihear.txt
    python compare.py --reference subtitles.txt --hypothesis mayihear.txt --save

Requirements:
    pip install jiwer>=3.0.0
"""

import argparse
import os
import re
import json
from datetime import datetime


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_metrics(reference: str, hypothesis: str) -> dict:
    try:
        from jiwer import wer, cer
    except ImportError:
        raise ImportError(
            "jiwer is required. Install with: pip install jiwer>=3.0.0"
        )

    ref_norm = normalize(reference)
    hyp_norm = normalize(hypothesis)

    wer_score = wer(ref_norm, hyp_norm)
    cer_score = cer(ref_norm, hyp_norm)

    ref_words = ref_norm.split()
    hyp_words = hyp_norm.split()

    ref_word_set = set(ref_words)
    hyp_word_set = set(hyp_words)
    matching_words = len(ref_word_set & hyp_word_set)

    return {
        "wer_pct": round(wer_score * 100, 2),
        "cer_pct": round(cer_score * 100, 2),
        "reference_word_count": len(ref_words),
        "hypothesis_word_count": len(hyp_words),
        "word_count_diff": abs(len(ref_words) - len(hyp_words)),
        "matching_unique_words": matching_words,
        "unique_words_in_reference": len(ref_word_set),
    }


def print_report(metrics: dict, ref_file: str, hyp_file: str) -> None:
    print()
    print("=" * 60)
    print("  MayiHear — Reporte de Precisión de Transcripción")
    print("=" * 60)
    print(f"  Referencia:  {ref_file}")
    print(f"  MayiHear:    {hyp_file}")
    print("-" * 60)
    print(f"  WER  (Word Error Rate)      : {metrics['wer_pct']:6.2f}%")
    print(f"  CER  (Character Error Rate) : {metrics['cer_pct']:6.2f}%")
    print("-" * 60)
    print(f"  Palabras en referencia      : {metrics['reference_word_count']}")
    print(f"  Palabras en MayiHear        : {metrics['hypothesis_word_count']}")
    print(f"  Diferencia de palabras      : {metrics['word_count_diff']}")
    print(f"  Palabras únicas coincidentes: {metrics['matching_unique_words']} / {metrics['unique_words_in_reference']}")
    print("=" * 60)

    wer = metrics["wer_pct"]
    if wer < 10:
        grade = "Excelente"
    elif wer < 20:
        grade = "Bueno"
    elif wer < 35:
        grade = "Aceptable"
    else:
        grade = "Necesita mejora"

    print(f"  Calificación: {grade} (WER {wer:.1f}%)")
    print("=" * 60)
    print()


def save_report(metrics: dict, ref_file: str, hyp_file: str) -> str:
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(results_dir, f"report_{timestamp}.json")

    report = {
        "timestamp": datetime.now().isoformat(),
        "reference_file": ref_file,
        "hypothesis_file": hyp_file,
        "metrics": metrics,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Compara transcripciones de MayiHear contra una referencia (WER/CER)."
    )
    parser.add_argument(
        "--reference", "-r", required=True,
        help="Archivo de transcripción de referencia (verdad de tierra)"
    )
    parser.add_argument(
        "--hypothesis", "-y", required=True,
        help="Archivo de transcripción generado por MayiHear"
    )
    parser.add_argument(
        "--save", "-s", action="store_true",
        help="Guarda el reporte JSON en accuracy_test/results/"
    )
    args = parser.parse_args()

    for path in [args.reference, args.hypothesis]:
        if not os.path.exists(path):
            print(f"Error: no se encontró el archivo '{path}'")
            raise SystemExit(1)

    with open(args.reference, "r", encoding="utf-8") as f:
        reference = f.read()

    with open(args.hypothesis, "r", encoding="utf-8") as f:
        hypothesis = f.read()

    metrics = compute_metrics(reference, hypothesis)
    print_report(metrics, args.reference, args.hypothesis)

    if args.save:
        out_path = save_report(metrics, args.reference, args.hypothesis)
        print(f"  Reporte guardado en: {out_path}\n")


if __name__ == "__main__":
    main()
