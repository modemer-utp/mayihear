"""
End-to-end pipeline test (local, no Lambda/SQS required):
  1. Fetch real transcript from Teams via Graph API
  2. Parse VTT to plain text
  3. Generate insights (Gemini)
  4. Generate acta (Gemini)
  5. Post to Monday.com (requires MONDAY_API_TOKEN + MONDAY_BOARD_ID in .env)

Run: python test_full_pipeline.py
"""
import json
import os
import requests
from datetime import date
from dotenv import load_dotenv

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda

load_dotenv("mayihear-api/.env")
load_dotenv("teams-pipeline/.env", override=False)

# ── Credentials ───────────────────────────────────────────────────────────────

TENANT_ID       = os.getenv("AZURE_TENANT_ID")
CLIENT_ID       = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET   = os.getenv("AZURE_CLIENT_SECRET")
ORGANIZER_EMAIL = os.getenv("ORGANIZER_TEAMS_MAIL", "sjulon@eya-tech.com")
USER_ID         = "e04212e3-6d89-46f3-b5da-72829cad7cdc"   # resolved once, stable
GRAPH_API       = "https://graph.microsoft.com/v1.0"

GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_TOKEN") or os.getenv("MONDAY_API_TOKEN")
MONDAY_BOARD_ID  = os.getenv("MONDAY_BOARD_ID", "18405594787")

DEFAULT_MODEL = "gemini-2.5-flash-lite"
GEMINI_BASE   = "https://generativelanguage.googleapis.com/v1beta/models"

# ── LangChain LLM (Gemini native REST wrapped as RunnableLambda) ─────────────
# Uses the proven REST endpoint. Compose with PromptTemplate | llm | StrOutputParser
# just like any LangChain chain.

def _gemini_call(prompt_value, model: str = DEFAULT_MODEL) -> str:
    """Invoke Gemini via native REST. Input is a LangChain StringPromptValue."""
    text = prompt_value.to_string() if hasattr(prompt_value, "to_string") else str(prompt_value)
    r = requests.post(
        f"{GEMINI_BASE}/{model}:generateContent?key={GEMINI_API_KEY}",
        json={"contents": [{"parts": [{"text": text}]}]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def build_llm(model: str = DEFAULT_MODEL) -> RunnableLambda:
    return RunnableLambda(lambda pv: _gemini_call(pv, model=model))

# ── Step 1: Fetch transcript from Teams ───────────────────────────────────────

def get_token() -> str:
    r = requests.post(
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_latest_transcript(token: str) -> tuple[str, str, str]:
    """Returns (meeting_id, transcript_id, subject) for the most recent transcript."""
    headers = {"Authorization": f"Bearer {token}"}

    url = f"{GRAPH_API}/users/{USER_ID}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{USER_ID}')"
    r = requests.get(url, headers=headers)
    r.raise_for_status()

    transcripts = r.json().get("value", [])
    if not transcripts:
        raise RuntimeError("No transcripts found via getAllTranscripts")

    # Most recent first
    transcripts.sort(key=lambda t: t.get("createdDateTime", ""), reverse=True)
    t = transcripts[0]

    meeting_id    = t["meetingId"]
    transcript_id = t["id"]
    created       = t.get("createdDateTime", "")
    print(f"[1/5] Found transcript  createdDateTime={created}")
    print(f"      meetingId    = {meeting_id[:50]}...")
    print(f"      transcriptId = {transcript_id[:50]}...")
    return meeting_id, transcript_id, created


def fetch_vtt(token: str, meeting_id: str, transcript_id: str) -> str:
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/vtt"}
    r = requests.get(
        f"{GRAPH_API}/users/{USER_ID}/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content",
        headers=headers,
    )
    r.raise_for_status()
    print(f"      VTT length = {len(r.text):,} chars")
    return r.text


# ── Step 2: Parse VTT ─────────────────────────────────────────────────────────

def parse_vtt(vtt: str) -> str:
    """Convert WebVTT to 'Speaker: text' lines, merging consecutive same-speaker turns."""
    import re
    lines = vtt.splitlines()
    segments = []
    for line in lines:
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        # Extract speaker tag <v Name>text</v>
        m = re.match(r"<v ([^>]+)>(.*)</v>", line)
        if m:
            speaker, text = m.group(1).strip(), m.group(2).strip()
        else:
            speaker, text = None, line

        if text:
            segments.append((speaker, text))

    # Merge consecutive same-speaker segments
    merged = []
    for speaker, text in segments:
        if merged and merged[-1][0] == speaker:
            merged[-1] = (speaker, merged[-1][1] + " " + text)
        else:
            merged.append([speaker, text])

    result = "\n".join(
        f"{sp}: {tx}" if sp else tx
        for sp, tx in merged
    )
    print(f"[2/5] Parsed transcript  {len(result):,} chars, {len(merged)} turns")
    return result


# ── Step 3 & 4: LangChain chains ─────────────────────────────────────────────

def generate_insights(transcript: str) -> dict:
    print("[3/5] Generating insights...")

    raw_template = open("mayihear-api/agents/prompts/generate_insights.prompt", encoding="utf-8").read()
    # LangChain PromptTemplate uses {var} — escape any literal braces in the template
    lc_template = raw_template.replace("{", "{{").replace("}", "}}") \
        .replace("{{transcript}}", "{transcript}") \
        .replace("{{user_context}}", "{user_context}")

    chain = (
        PromptTemplate.from_template(lc_template)
        | build_llm()
        | StrOutputParser()
    )

    raw = chain.invoke({
        "transcript": transcript,
        "user_context": "Reunion de equipo en UTP",
    })

    cleaned = raw.strip()
    if "```" in cleaned:
        start = cleaned.find("```")
        end   = cleaned.rfind("```")
        cleaned = cleaned[start:end].removeprefix("```json").removeprefix("```").strip()
    if not cleaned:
        print(f"[WARN] Empty insights response. Raw:\n{raw[:400]}")
        return {}
    return json.loads(cleaned)


def generate_acta(transcript: str) -> str:
    print("[4/5] Generating acta...")

    raw_template = open("mayihear-api/agents/prompts/generate_meeting_act.prompt", encoding="utf-8").read()
    lc_template = raw_template.replace("{", "{{").replace("}", "}}") \
        .replace("{{transcript}}", "{transcript}") \
        .replace("{{user_context}}", "{user_context}") \
        .replace("{{today_date}}", "{today_date}")

    chain = (
        PromptTemplate.from_template(lc_template)
        | build_llm()
        | StrOutputParser()
    )

    return chain.invoke({
        "transcript": transcript,
        "user_context": "Reunion de equipo en UTP",
        "today_date": str(date.today()),
    })


# ── Step 5: Post to Monday.com ────────────────────────────────────────────────

MONDAY_API_URL = "https://api.monday.com/v2"


def _monday_gql(query: str, variables: dict = None) -> dict:
    headers = {
        "Authorization": f"Bearer {MONDAY_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    r = requests.post(MONDAY_API_URL, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Monday: {data['errors'][0]['message']}")
    return data["data"]


def _ensure_insights_column() -> str:
    """Return the column_id for the 'Insights' long_text column, creating it if needed."""
    data = _monday_gql(
        "query($ids:[ID!]!){ boards(ids:$ids){ columns{ id title } } }",
        {"ids": [MONDAY_BOARD_ID]},
    )
    for col in data["boards"][0]["columns"]:
        if col["title"].lower() == "insights":
            return col["id"]
    data = _monday_gql(
        f'mutation{{ create_column(board_id:{MONDAY_BOARD_ID}, title:"Insights", column_type:long_text){{ id }} }}'
    )
    return data["create_column"]["id"]


def post_to_monday(subject: str, insights: dict, acta: str):
    if not MONDAY_API_TOKEN:
        print("[5/5] SKIP Monday.com — no token found")
        return None

    # Create item
    data = _monday_gql(
        "mutation($board_id:ID!, $item_name:String!){ create_item(board_id:$board_id, item_name:$item_name){ id } }",
        {"board_id": MONDAY_BOARD_ID, "item_name": subject},
    )
    item_id = data["create_item"]["id"]

    # Build insights text
    summary_text   = "\n".join(f"• {p}" for p in insights.get("summary", []))
    decisions_text = "\n".join(f"• {d}" for d in insights.get("decisions", []))
    actions_text   = "\n".join(
        f"• [{a.get('person','')}] {a.get('task', a)}"
        if isinstance(a, dict) else f"• {a}"
        for a in insights.get("action_items", [])
    )
    questions_text = "\n".join(f"• {q}" for q in insights.get("open_questions", []))
    insights_text  = (
        f"RESUMEN\n{summary_text}\n\n"
        f"DECISIONES\n{decisions_text}\n\n"
        f"TAREAS\n{actions_text}\n\n"
        f"PREGUNTAS ABIERTAS\n{questions_text}"
    )

    # Write to Insights column
    col_id = _ensure_insights_column()
    _monday_gql(
        """mutation($board_id:ID!, $item_id:ID!, $column_id:String!, $value:JSON!){
          change_column_value(board_id:$board_id, item_id:$item_id, column_id:$column_id, value:$value){ id }
        }""",
        {
            "board_id": MONDAY_BOARD_ID,
            "item_id": item_id,
            "column_id": col_id,
            "value": json.dumps({"text": insights_text}),
        },
    )

    print(f"[5/5] Posted to Monday.com  board={MONDAY_BOARD_ID}  item={item_id}  name='{subject}'")
    return item_id


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("mayihear Full Pipeline Test")
    print("=" * 60)

    # 1. Fetch transcript from Teams
    token = get_token()
    meeting_id, transcript_id, subject = fetch_latest_transcript(token)
    vtt = fetch_vtt(token, meeting_id, transcript_id)

    # 2. Parse
    transcript_text = parse_vtt(vtt)

    # 3. Insights
    insights = generate_insights(transcript_text)
    print(f"      summary items    = {len(insights.get('summary', []))}")
    print(f"      decisions        = {len(insights.get('decisions', []))}")
    print(f"      action_items     = {len(insights.get('action_items', []))}")

    # 4. Acta
    acta = generate_acta(transcript_text)
    print(f"      acta length      = {len(acta):,} chars")

    # 5. Monday.com
    item_id = post_to_monday(subject, insights, acta)

    # ── Print results ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)

    print("\n-- INSIGHTS --")
    print(json.dumps(insights, ensure_ascii=False, indent=2))

    print("\n-- ACTA (preview, first 800 chars) --")
    print(acta[:800])

    if item_id:
        print(f"\n-- MONDAY ITEM ID: {item_id} --")


if __name__ == "__main__":
    main()
