import os
import json
from google import genai

_client = None

INSIGHTS_PROMPT = """\
Eres un asistente de reuniones para ejecutivos y directores ocupados.
Tu trabajo es extraer insights estructurados y accionables de las transcripciones de reuniones.
Responde siempre en español, sin importar el idioma de la transcripción.

== REGLA DE ORO ==
Preserva literalmente toda información de valor para la toma de decisiones:
- Datos cuantitativos: números, porcentajes, montos, horas, costos, rangos, estimaciones
- Datos cualitativos clave: nombres de modelos/herramientas/configuraciones, versiones, comparativas
- Razonamientos: si una decisión tiene un dato o argumento que la sustenta, inclúyelo
NO parafrasees ni omitas datos concretos.
==

Analiza la siguiente transcripción y devuelve un JSON con exactamente estos campos:
- summary: lista de strings, un punto por tema relevante con datos concretos
- decisions: lista de strings, cada decisión tomada con su razonamiento
- action_items: lista de strings, cada tarea con responsable y descripción completa
- open_questions: lista de strings, temas no resueltos o que requieren seguimiento

Transcripción:
{transcript}

Responde SOLO con el JSON válido, sin texto adicional ni markdown.
"""


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def generate_insights(transcript: str) -> dict:
    client = _get_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=INSIGHTS_PROMPT.format(transcript=transcript),
    )
    raw = response.text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def format_insights_for_monday(insights: dict) -> str:
    """Format insights dict into a readable text block for Monday.com long-text column."""
    lines = []

    if insights.get("summary"):
        lines.append("📋 RESUMEN")
        for point in insights["summary"]:
            lines.append(f"• {point}")
        lines.append("")

    if insights.get("decisions"):
        lines.append("✅ DECISIONES")
        for d in insights["decisions"]:
            lines.append(f"• {d}")
        lines.append("")

    if insights.get("action_items"):
        lines.append("🎯 TAREAS")
        for a in insights["action_items"]:
            lines.append(f"• {a}")
        lines.append("")

    if insights.get("open_questions"):
        lines.append("❓ PREGUNTAS ABIERTAS")
        for q in insights["open_questions"]:
            lines.append(f"• {q}")

    return "\n".join(lines)
