"""
Lambda: transcript_processor
Triggered by SQS. For each message:
  1. Fetch VTT transcript from Graph API
  2. Parse VTT -> plain text
  3. Generate insights (LangChain + Gemini Flash Lite)
  4. Generate acta   (LangChain + Gemini Flash Lite)
  5. Post results to Monday.com
"""
import json
import os
import requests

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

from utils.graph_client import get_token, get_transcript_content
from utils.vtt_parser import parse_vtt

MONDAY_API_URL   = "https://api.monday.com/v2"
LLM_API_KEY      = os.environ["LLM_API_KEY"]
MONDAY_API_TOKEN = os.environ["MONDAY_API_TOKEN"]
MONDAY_BOARD_ID  = os.environ["MONDAY_BOARD_ID"]

DEFAULT_MODEL = "gemini-2.5-flash-lite"
GEMINI_BASE   = "https://generativelanguage.googleapis.com/v1beta/models"


# ── LangChain LLM (Gemini native REST — no gRPC, Lambda-safe) ────────────────

def _gemini_call(prompt_value, model: str = DEFAULT_MODEL) -> str:
    text = prompt_value.to_string() if hasattr(prompt_value, "to_string") else str(prompt_value)
    r = requests.post(
        f"{GEMINI_BASE}/{model}:generateContent?key={LLM_API_KEY}",
        json={"contents": [{"parts": [{"text": text}]}]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def build_llm(model: str = DEFAULT_MODEL) -> RunnableLambda:
    return RunnableLambda(lambda pv: _gemini_call(pv, model=model))


# ── Prompts ───────────────────────────────────────────────────────────────────

INSIGHTS_TEMPLATE = """\
Eres un asistente de reuniones para ejecutivos y directores ocupados.
Tu trabajo es extraer insights estructurados y accionables de las transcripciones de reuniones.
Responde siempre en español.

Analiza la siguiente transcripción y devuelve un JSON con exactamente estos campos:
- summary: lista de puntos clave con datos concretos
- decisions: decisiones tomadas con su razonamiento
- action_items: tareas con responsable y descripción
- open_questions: temas no resueltos

Transcripción:
{transcript}

Responde SOLO con el JSON, sin texto adicional.\
"""

ACTA_TEMPLATE = """\
Eres un asistente que genera actas de reunión formales en español.
Basándote en la siguiente transcripción, genera un acta estructurada con:
- Fecha y participantes
- Temas tratados
- Acuerdos y decisiones
- Tareas y responsables
- Próximos pasos

Transcripción:
{transcript}\
"""


# ── LangChain chains ──────────────────────────────────────────────────────────

insights_chain = (
    PromptTemplate.from_template(INSIGHTS_TEMPLATE)
    | build_llm()
    | StrOutputParser()
)

acta_chain = (
    PromptTemplate.from_template(ACTA_TEMPLATE)
    | build_llm()
    | StrOutputParser()
)


def generate_insights(transcript: str) -> dict:
    raw = insights_chain.invoke({"transcript": transcript})
    cleaned = raw.strip()
    if "```" in cleaned:
        start = cleaned.find("```")
        end   = cleaned.rfind("```")
        cleaned = cleaned[start:end].removeprefix("```json").removeprefix("```").strip()
    return json.loads(cleaned)


def generate_acta(transcript: str) -> str:
    return acta_chain.invoke({"transcript": transcript})


# ── Monday.com ────────────────────────────────────────────────────────────────

def post_to_monday(subject: str, insights: dict, acta: str):
    headers = {
        "Authorization": f"Bearer {MONDAY_API_TOKEN}",
        "Content-Type": "application/json",
    }

    r = requests.post(MONDAY_API_URL, json={
        "query": """
            mutation($board_id: ID!, $item_name: String!) {
              create_item(board_id: $board_id, item_name: $item_name) { id }
            }
        """,
        "variables": {"board_id": MONDAY_BOARD_ID, "item_name": subject},
    }, headers=headers, timeout=30)
    r.raise_for_status()
    item_id = r.json()["data"]["create_item"]["id"]

    summary_text   = "\n".join(f"• {p}" for p in insights.get("summary", []))
    decisions_text = "\n".join(f"• {d}" for d in insights.get("decisions", []))
    actions_text   = "\n".join(
        f"• [{a.get('person','')}] {a.get('task', a)}"
        if isinstance(a, dict) else f"• {a}"
        for a in insights.get("action_items", [])
    )
    body = f"**Resumen**\n{summary_text}\n\n**Decisiones**\n{decisions_text}\n\n**Tareas**\n{actions_text}"

    requests.post(MONDAY_API_URL, json={
        "query": """
            mutation($item_id: ID!, $body: String!) {
              create_update(item_id: $item_id, body: $body) { id }
            }
        """,
        "variables": {"item_id": item_id, "body": body},
    }, headers=headers, timeout=30)

    print(f"[OK] Posted to Monday item {item_id}: {subject}")
    return item_id


# ── Lambda handler ────────────────────────────────────────────────────────────

def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])

        organizer_email = body["organizer_email"]
        meeting_id      = body["meeting_id"]
        transcript_id   = body["transcript_id"]
        subject         = body.get("subject", "Reunion Teams")

        print(f"[INFO] Processing: {subject}")

        token        = get_token()
        vtt_content  = get_transcript_content(token, organizer_email, meeting_id, transcript_id)
        transcript   = parse_vtt(vtt_content)
        print(f"[INFO] Transcript: {len(transcript)} chars")

        insights = generate_insights(transcript)
        acta     = generate_acta(transcript)
        post_to_monday(subject, insights, acta)

    return {"statusCode": 200}
