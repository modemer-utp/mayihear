import os
import requests

MONDAY_API = "https://api.monday.com/v2"
INSIGHTS_COLUMN_ID = "insights"  # Monday column ID — set after running setup_board()


def list_boards() -> list:
    """Returns list of {id, name} for all accessible boards (max 30)."""
    query = "query { boards(limit: 30, order_by: created_at) { id name } }"
    r = requests.post(MONDAY_API, json={"query": query}, headers=_headers())
    r.raise_for_status()
    return [{"id": b["id"], "name": b["name"]} for b in r.json()["data"]["boards"]]


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
