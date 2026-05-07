import os
import datetime
import requests

MONDAY_API = "https://api.monday.com/v2"
INSIGHTS_COLUMN_ID = "insights"  # Monday column ID — set after running setup_board()

# Cache: board_id → actualizaciones item_id
_actualizaciones_item_cache: dict = {}


def list_boards() -> list:
    """Returns relevant boards — excludes sub_items_boards and noise."""
    query = "query { boards(limit: 50, order_by: used_at) { id name type } }"
    r = requests.post(MONDAY_API, json={"query": query}, headers=_headers())
    r.raise_for_status()
    return [
        {"id": b["id"], "name": b["name"]}
        for b in r.json()["data"]["boards"]
        if b.get("type") not in ("sub_items_board", "document")
    ]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['MONDAY_TOKEN']}",
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }


def setup_board(board_id: str) -> str:
    """
    Ensures an 'insights' long-text column exists on the board.
    Returns the column ID. Call this once during setup.
    """
    # Check existing columns
    query = """
    query($board_id: ID!) {
      boards(ids: [$board_id]) {
        columns { id title type }
      }
    }
    """
    r = requests.post(MONDAY_API, json={"query": query, "variables": {"board_id": board_id}}, headers=_headers())
    r.raise_for_status()
    columns = r.json()["data"]["boards"][0]["columns"]

    for col in columns:
        if col["title"].lower() == "insights":
            print(f"[Monday] Found existing 'insights' column: {col['id']}")
            return col["id"]

    # Create the column
    mutation = """
    mutation($board_id: ID!, $title: String!, $column_type: ColumnType!) {
      create_column(board_id: $board_id, title: $title, column_type: $column_type) {
        id title
      }
    }
    """
    r = requests.post(MONDAY_API, json={
        "query": mutation,
        "variables": {
            "board_id": board_id,
            "title": "Insights",
            "column_type": "long_text",
        },
    }, headers=_headers())
    r.raise_for_status()
    col_id = r.json()["data"]["create_column"]["id"]
    print(f"[Monday] Created 'Insights' column: {col_id}")
    return col_id


def create_meeting_item(board_id: str, meeting_name: str, insights_text: str, insights_column_id: str) -> str:
    """
    Creates a new item on the board with the meeting name and fills the insights column.
    Returns the new item ID.
    """
    import json as _json

    # Step 1: create the item
    create_mutation = """
    mutation($board_id: ID!, $item_name: String!) {
      create_item(board_id: $board_id, item_name: $item_name) { id }
    }
    """
    r = requests.post(MONDAY_API, json={
        "query": create_mutation,
        "variables": {"board_id": board_id, "item_name": meeting_name},
    }, headers=_headers())
    r.raise_for_status()
    item_id = r.json()["data"]["create_item"]["id"]
    print(f"[Monday] Created item '{meeting_name}' → id={item_id}")

    # Step 2: fill the insights column
    column_values = _json.dumps({insights_column_id: {"text": insights_text}})
    update_mutation = """
    mutation($item_id: ID!, $board_id: ID!, $column_values: JSON!) {
      change_multiple_column_values(item_id: $item_id, board_id: $board_id, column_values: $column_values) {
        id
      }
    }
    """
    r = requests.post(MONDAY_API, json={
        "query": update_mutation,
        "variables": {
            "item_id": item_id,
            "board_id": board_id,
            "column_values": column_values,
        },
    }, headers=_headers())
    r.raise_for_status()
    print(f"[Monday] Insights written to item {item_id}")
    return item_id


def find_or_create_actualizaciones_item(board_id: str) -> str:
    """
    Finds the item named 'Actualizaciones' on the board, or creates it.
    Returns the item_id. Cached in memory.
    """
    if board_id in _actualizaciones_item_cache:
        return _actualizaciones_item_cache[board_id]

    # Search existing items
    query = """
    query($board_id: ID!) {
      boards(ids: [$board_id]) {
        items_page(limit: 100) {
          items { id name }
        }
      }
    }
    """
    r = requests.post(MONDAY_API, json={"query": query, "variables": {"board_id": board_id}}, headers=_headers())
    r.raise_for_status()
    items = r.json()["data"]["boards"][0]["items_page"]["items"]
    for item in items:
        if item["name"].lower() in ("actualizaciones", "updates", "reuniones"):
            _actualizaciones_item_cache[board_id] = item["id"]
            return item["id"]

    # Not found — create it
    mutation = """
    mutation($board_id: ID!, $item_name: String!) {
      create_item(board_id: $board_id, item_name: $item_name, create_labels_if_missing: true) { id }
    }
    """
    r = requests.post(MONDAY_API, json={
        "query": mutation,
        "variables": {"board_id": board_id, "item_name": "Actualizaciones"},
    }, headers=_headers())
    r.raise_for_status()
    item_id = r.json()["data"]["create_item"]["id"]
    _actualizaciones_item_cache[board_id] = item_id
    print(f"[Monday] Created 'Actualizaciones' item on board {board_id} → {item_id}")
    return item_id


def post_meeting_update(board_id: str, subject: str, insights_text: str) -> str:
    """
    Posts meeting insights as an Update (Actualizaciones) on the board's
    dedicated 'Actualizaciones' item. Returns the update id.
    Updates are shown newest-first in Monday automatically.
    """
    item_id = find_or_create_actualizaciones_item(board_id)

    # Build a nicely formatted update body (HTML supported in Monday updates)
    peru_now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=5)
    date_str = peru_now.strftime("%d/%m/%Y — %I:%M %p")

    body = (
        f"<h3>📝 {subject}</h3>"
        f"<p><strong>Generado:</strong> {date_str} (Lima)</p>"
        f"<p>{'─' * 40}</p>"
        + "".join(
            f"<p>{line}</p>" if line.strip() else "<br/>"
            for line in insights_text.splitlines()
        )
    )

    mutation = """
    mutation ($item_id: ID!, $body: String!) {
        create_update(item_id: $item_id, body: $body) { id }
    }
    """
    r = requests.post(MONDAY_API, json={
        "query": mutation,
        "variables": {"item_id": item_id, "body": body},
    }, headers=_headers())
    r.raise_for_status()
    update_id = r.json()["data"]["create_update"]["id"]
    print(f"[Monday] Posted update to 'Actualizaciones' item {item_id} -> update {update_id}")
    return update_id
