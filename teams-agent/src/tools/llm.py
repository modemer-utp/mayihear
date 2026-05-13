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

GEMINI_MODEL = "gemini-2.5-flash"


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


CUSTOM_PROMPT_WRAPPER = """\
Tu tarea es generar un documento a partir de una transcripción de reunión.

== INSTRUCCIÓN / PLANTILLA ==
{custom_prompt}
== FIN DE INSTRUCCIÓN ==

REGLAS IMPORTANTES:
- Si la instrucción o plantilla contiene datos de ejemplo (nombres, fechas, cifras, etc.), úsalos ÚNICAMENTE como referencia de formato y estructura. NO los copies al output.
- Extrae toda la información del output EXCLUSIVAMENTE de la transcripción.
- Si un dato no aparece en la transcripción, escribe N/D.
- Responde siempre en español.

== TRANSCRIPCIÓN ==
{transcript}
== FIN DE TRANSCRIPCIÓN ==
"""


def generate_insights_custom(transcript: str, custom_prompt: str) -> str:
    """Generate insights using a user-defined prompt. Returns plain text."""
    response = _get_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=CUSTOM_PROMPT_WRAPPER.format(
            custom_prompt=custom_prompt.strip(),
            transcript=transcript,
        ),
    )
    return response.text.strip()


def generate_insights(transcript: str) -> dict:
    response = _get_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=INSIGHTS_PROMPT.format(transcript=transcript),
    )
    raw = response.text.strip()
    # Strip markdown fences
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Gemini sometimes returns truncated JSON — attempt to salvage by finding
        # the last complete array and closing the object
        import re
        fixed = raw
        # Remove any trailing incomplete entry (unmatched quote or partial string)
        fixed = re.sub(r',\s*"[^"]*$', '', fixed)   # trailing incomplete key
        fixed = re.sub(r',\s*"[^"]*":\s*"[^"]*$', '', fixed)  # incomplete value
        # Close any open arrays and the root object
        open_arrays = fixed.count('[') - fixed.count(']')
        open_braces = fixed.count('{') - fixed.count('}')
        fixed += ']' * max(open_arrays, 0) + '}' * max(open_braces, 0)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            # Final fallback: return the raw text as a summary bullet
            return {"summary": [raw[:2000]], "decisions": [], "action_items": [], "open_questions": []}


def format_insights_for_monday(insights: dict) -> str:
    """Verbose format for Monday.com long-text column."""
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


def format_insights_for_teams(insights: dict) -> str:
    """Fallback plain-text format (used when Adaptive Card is not available)."""
    lines = []
    for emoji, title, key in [
        ("📋", "Resumen", "summary"),
        ("✅", "Decisiones", "decisions"),
        ("🎯", "Tareas", "action_items"),
        ("❓", "Preguntas abiertas", "open_questions"),
    ]:
        items = insights.get(key, [])
        if items:
            lines.append(f"{emoji} **{title}**")
            lines += [f"• {i}" for i in items]
            lines.append("")
    return "\n".join(lines).strip()
