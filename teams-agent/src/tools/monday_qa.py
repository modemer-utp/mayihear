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
Eres un asistente de productividad que responde preguntas sobre el tablero de Monday.com de la empresa.
Responde SIEMPRE en español, de forma concisa y directa.
Basa tu respuesta ÚNICAMENTE en los datos del tablero proporcionados.
Si la información no está disponible, dilo claramente.

== DATOS DEL TABLERO "{board_name}" ==
{board_data}
== FIN DE DATOS ==

Pregunta: {question}

Responde de forma clara. Si hay tareas, decisiones u otros elementos específicos, enuméralos con viñetas.
No inventes información que no esté en los datos.
"""


def _monday_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['MONDAY_TOKEN']}",
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }


def fetch_board_items(board_id: str) -> dict:
    """
    Fetch up to 200 items from a board with all column values.
    Returns {"name": str, "items": [...]}
    """
    query = """
    query($board_id: ID!) {
      boards(ids: [$board_id]) {
        name
        items_page(limit: 200) {
          items {
            id
            name
            state
            group { title }
            column_values {
              id
              text
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
        timeout=15,
    )
    r.raise_for_status()
    boards = r.json().get("data", {}).get("boards", [])
    if not boards:
        return {"name": "Desconocido", "items": []}
    board = boards[0]
    items = board["items_page"]["items"]
    return {"name": board["name"], "items": items}


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
    items = board_data["items"]

    if not items:
        return f"El tablero **{name}** no tiene ítems disponibles."

    # Compact JSON — preserve column text values, drop empty ones
    compact_items = []
    for item in items:
        cols = {cv["id"]: cv["text"] for cv in item.get("column_values", []) if cv.get("text")}
        compact_items.append({
            "id": item["id"],
            "name": item["name"],
            "grupo": item.get("group", {}).get("title", ""),
            **cols,
        })

    board_data_str = json.dumps(compact_items, ensure_ascii=False, separators=(",", ":"))

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=_QA_PROMPT.format(
            board_name=name,
            board_data=board_data_str,
            question=question,
        ),
    )
    return response.text.strip()
