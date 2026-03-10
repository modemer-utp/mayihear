import requests
from infrastructure.utilities.secret_manager import get_monday_api_token

MONDAY_API_URL = "https://api.monday.com/v2"


def _gql(query: str, variables: dict = None) -> dict:
    token = get_monday_api_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    resp = requests.post(MONDAY_API_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday.com: {data['errors'][0]['message']}")
    return data["data"]


def get_boards() -> list:
    query = "{ boards(limit: 50, order_by: used_at) { id name } }"
    return _gql(query)["boards"]


def get_items(board_id: str) -> list:
    query = """
    query($ids: [ID!]!) {
      boards(ids: $ids) {
        items_page(limit: 200) {
          items { id name }
        }
      }
    }
    """
    data = _gql(query, {"ids": [board_id]})
    return data["boards"][0]["items_page"]["items"]


def get_columns(board_id: str) -> list:
    query = """
    query($ids: [ID!]!) {
      boards(ids: $ids) {
        columns { id title type }
      }
    }
    """
    data = _gql(query, {"ids": [board_id]})
    return data["boards"][0]["columns"]


def post_update(item_id: str, body: str) -> str:
    mutation = """
    mutation($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) { id }
    }
    """
    return str(_gql(mutation, {"item_id": item_id, "body": body})["create_update"]["id"])


def get_board_items(board_id: str) -> list:
    query = """
    query($ids: [ID!]!) {
      boards(ids: $ids) {
        items_page(limit: 200) {
          items { id name }
        }
      }
    }
    """
    data = _gql(query, {"ids": [board_id]})
    return data["boards"][0]["items_page"]["items"]


def update_long_text_column(board_id: str, item_id: str, column_id: str, text: str) -> str:
    import json as _json
    mutation = """
    mutation($board_id: ID!, $item_id: ID!, $column_id: String!, $value: JSON!) {
      change_column_value(
        board_id: $board_id
        item_id: $item_id
        column_id: $column_id
        value: $value
      ) { id }
    }
    """
    return str(_gql(mutation, {
        "board_id": board_id,
        "item_id": item_id,
        "column_id": column_id,
        "value": _json.dumps({"text": text}),
    })["change_column_value"]["id"])


def update_column(board_id: str, item_id: str, column_id: str, value: str) -> str:
    mutation = """
    mutation($board_id: ID!, $item_id: ID!, $column_id: String!, $value: String!) {
      change_simple_column_value(
        board_id: $board_id
        item_id: $item_id
        column_id: $column_id
        value: $value
      ) { id }
    }
    """
    return str(_gql(mutation, {
        "board_id": board_id,
        "item_id": item_id,
        "column_id": column_id,
        "value": value,
    })["change_simple_column_value"]["id"])
