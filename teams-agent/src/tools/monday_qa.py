"""
Monday.com Q&A tool.
Fetches board items and answers natural-language questions using Gemini.

Approach: live query — always fresh, no extra storage.
For boards with >500 items consider adding a sync/cache layer.
"""
import os
import json
import logging
import requests
from google import genai

logger = logging.getLogger(__name__)
MONDAY_API = "https://api.monday.com/v2"

_QA_PROMPT = """\
Eres un asistente de productividad para el equipo de Producto Digital de UTP (Universidad Tecnológica del Perú).
Responde SIEMPRE en español, de forma concisa y directa.
Basa tu respuesta ÚNICAMENTE en los datos del tablero proporcionados.

El contexto corresponde al roadmap de proyectos de UTP.
Cada ítem es una iniciativa con su responsable, sponsor, estado, prioridad, KPIs, fase, presupuesto y subitems (actividades, tareas, etc.).
Algunos proyectos tienen un campo "Enlace" con una URL a un tablero vinculado que contiene más detalle.

== DATOS DEL TABLERO "{board_name}" — GRUPO: {group_name} ==
{board_data}
== FIN DE DATOS ==

Pregunta: {question}

REGLAS:
- Responde con viñetas cuando hay listas de proyectos, responsables, estados, actividades, etc.
- Si el proyecto tiene subitems, inclúyelos en tu respuesta cuando sean relevantes.
- Si el proyecto tiene un campo "Enlace" (tablero vinculado) y los detalles pedidos no están en los datos actuales, menciona que más información está disponible en ese enlace.
- No inventes información que no esté en los datos.
"""


def _monday_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['MONDAY_TOKEN']}",
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }


def fetch_actualizaciones_updates(board_id: str) -> list[dict]:
    """
    Fetch updates (Monday 'Actualizaciones') from the dedicated 'Actualizaciones' item on the board.
    Returns list of {subject, body, created_at}.
    """
    # Find the Actualizaciones item
    query = """
    query($board_id: ID!) {
      boards(ids: [$board_id]) {
        items_page(limit: 50) {
          items { id name }
        }
      }
    }
    """
    try:
        r = requests.post(MONDAY_API, json={"query": query, "variables": {"board_id": board_id}},
                          headers=_monday_headers(), timeout=10)
        r.raise_for_status()
        boards = r.json().get("data", {}).get("boards", [])
        if not boards:
            return []
        items = boards[0]["items_page"]["items"]
        actualizaciones_id = None
        for item in items:
            if item["name"].lower() in ("actualizaciones", "updates", "reuniones"):
                actualizaciones_id = item["id"]
                break
        if not actualizaciones_id:
            return []

        # Fetch updates on that item
        updates_query = """
        query($item_id: ID!) {
          items(ids: [$item_id]) {
            updates(limit: 100) {
              id body created_at
            }
          }
        }
        """
        r2 = requests.post(MONDAY_API, json={"query": updates_query, "variables": {"item_id": actualizaciones_id}},
                           headers=_monday_headers(), timeout=15)
        r2.raise_for_status()
        items_data = r2.json().get("data", {}).get("items", [])
        if not items_data:
            return []
        return items_data[0].get("updates", [])
    except Exception as e:
        logger.warning(f"Could not fetch actualizaciones updates: {e}")
        return []


def fetch_board_items(board_id: str) -> dict:
    """
    Fetch items from all configured groups (MONDAY_GROUP_IDS, comma-separated).
    Falls back to all board items if no groups configured.
    Returns {"name": str, "group": str, "items": [...]}
    """
    group_ids = [g.strip() for g in os.environ.get("MONDAY_GROUP_IDS", os.environ.get("MONDAY_GROUP_ID", "")).split(",") if g.strip()]

    if group_ids:
        query = """
        query($board_id: ID!, $group_ids: [String!]!) {
          boards(ids: [$board_id]) {
            name
            groups(ids: $group_ids) {
              title
              items_page(limit: 200) {
                items {
                  id
                  name
                  column_values {
                    text
                    value
                    column { title type }
                    ... on FormulaValue { display_value }
                    ... on MirrorValue { display_value }
                    ... on NumbersValue { number }
                    ... on TimelineValue { from to }
                    ... on LinkValue { url text }
                  }
                  subitems {
                    id
                    name
                    column_values {
                      text
                      value
                      column { title type }
                      ... on FormulaValue { display_value }
                      ... on NumbersValue { number }
                    }
                  }
                }
              }
            }
          }
        }
        """
        r = requests.post(
            MONDAY_API,
            json={"query": query, "variables": {"board_id": board_id, "group_ids": group_ids}},
            headers=_monday_headers(),
            timeout=20,
        )
        r.raise_for_status()
        boards = r.json().get("data", {}).get("boards", [])
        if not boards:
            return {"name": "Desconocido", "group": "", "items": []}

        board = boards[0]
        all_items = []
        group_names = []
        for group in board.get("groups", []):
            group_names.append(group["title"])
            for item in group["items_page"]["items"]:
                item["_group"] = group["title"]
                all_items.append(item)
        return {"name": board["name"], "group": " + ".join(group_names), "items": all_items}
    else:
        query = """
        query($board_id: ID!) {
          boards(ids: [$board_id]) {
            name
            items_page(limit: 200) {
              items {
                id name
                group { title }
                column_values {
                  text value
                  column { title type }
                  ... on FormulaValue { display_value }
                  ... on MirrorValue { display_value }
                  ... on NumbersValue { number }
                  ... on TimelineValue { from to }
                  ... on LinkValue { url text }
                }
                subitems {
                  id name
                  column_values {
                    text value
                    column { title type }
                    ... on FormulaValue { display_value }
                    ... on NumbersValue { number }
                  }
                }
              }
            }
          }
        }
        """
        r = requests.post(
            MONDAY_API,
            json={"query": query, "variables": {"board_id": board_id}},
            headers=_monday_headers(),
            timeout=20,
        )
        r.raise_for_status()
        boards = r.json().get("data", {}).get("boards", [])
        if not boards:
            return {"name": "Desconocido", "group": "", "items": []}
        board = boards[0]
        return {"name": board["name"], "group": "", "items": board["items_page"]["items"]}


def _resolve_cv(cv: dict):
    """
    Extract the best display value from a Monday column_value.
    Priority: inline fragment fields → text → value (raw JSON fallback).
    Returns None if nothing useful found.
    """
    col_type = (cv.get("column") or {}).get("type", "")

    # Formula / Mirror → display_value
    dv = (cv.get("display_value") or "").strip()
    if dv:
        return dv

    # Numbers → number field
    num = cv.get("number")
    if num is not None:
        return str(num)

    # Timeline → from/to
    if col_type == "timeline" and (cv.get("from") or cv.get("to")):
        return f"{cv.get('from', '')} - {cv.get('to', '')}".strip(" -")

    # Link → text + url
    if col_type == "link":
        link_text = cv.get("text") or ""
        url = cv.get("url") or ""
        if url:
            return f"{link_text} - {url}" if link_text else url

    # Standard text field
    text = (cv.get("text") or "").strip()
    if text:
        return text

    return None


def ask_monday(question: str, board_id: str, board_name: str = "") -> str:
    """
    Answer a natural-language question about Monday board data using Gemini.

    For simple questions ("¿qué tarea quedó pendiente?") this is instant.
    For analytical questions ("¿qué proyecto se ha retrasado más?") Gemini
    reasons over all the fetched items — no extra DB needed for boards < 500 items.

    Returns a natural-language answer string.
    """
    board_data = fetch_board_items(board_id)
    name = board_name or board_data["name"]
    group_name = board_data.get("group", "")
    items = board_data["items"]

    if not items:
        return f"El tablero **{name}** no tiene ítems disponibles."

    # Compact JSON — use column titles as keys, resolve text vs value per type
    compact_items = []
    for item in items:
        cols = {}
        for cv in item.get("column_values", []):
            resolved = _resolve_cv(cv)
            if resolved is not None:
                cols[cv["column"]["title"]] = resolved
        grupo = item.get("_group") or (item.get("group") or {}).get("title", "")
        row = {"proyecto": item["name"], "grupo": grupo, **cols}
        if item.get("subitems"):
            row["subitems"] = [
                {
                    "nombre": s["name"],
                    **{
                        sv["column"]["title"]: _resolve_cv(sv)
                        for sv in s.get("column_values", [])
                        if _resolve_cv(sv) is not None
                    },
                }
                for s in item["subitems"]
            ]
        compact_items.append(row)

    board_data_str = json.dumps(compact_items, ensure_ascii=False, separators=(",", ":"))

    # Append meeting updates (Actualizaciones) section if available
    updates = fetch_actualizaciones_updates(board_id)
    updates_section = ""
    if updates:
        import re as _re
        updates_section = "\n\n== ACTUALIZACIONES DE REUNIONES (más recientes primero) ==\n"
        for u in updates:
            # Strip HTML tags for readability
            body_clean = _re.sub(r"<[^>]+>", " ", u.get("body", "")).strip()
            body_clean = _re.sub(r"\s+", " ", body_clean)
            updates_section += f"[{u.get('created_at', '')}] {body_clean}\n"
        updates_section += "== FIN ACTUALIZACIONES =="

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=_QA_PROMPT.format(
            board_name=name,
            group_name=group_name,
            board_data=board_data_str + updates_section,
            question=question,
        ),
    )
    return response.text.strip()
