import os
import requests
from dotenv import load_dotenv

load_dotenv()

import os

os.environ['MONDAY_API_KEY'] = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjYyOTYwNzQwMiwiYWFpIjoxMSwidWlkIjoxMDA2NjA3MDgsImlhZCI6IjIwMjYtMDMtMDVUMjM6MDk6MDAuMjIxWiIsInBlciI6Im1lOndyaXRlIiwiYWN0aWQiOjM0MDk2NTU3LCJyZ24iOiJ1c2UxIn0.GlBVqKM0GSUe3P2vT4vcR8nA6AFmOkkkfJ0vlKi1cZY"

API_URL = "https://api.monday.com/v2"
API_KEY = os.getenv("MONDAY_API_KEY")


def _run_query(query: str, variables: dict | None = None):
    headers = {
        "Authorization": API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "query": query,
        "variables": variables or {}
    }

    r = requests.post(API_URL, json=payload, headers=headers)
    r.raise_for_status()
    return r.json()


# -------------------------------------------------
# 1. List boards
# -------------------------------------------------

def list_boards():
    """
    Returns all boards with their ids.
    Useful for agents to discover available boards.
    """

    query = """
    query {
        boards {
            id
            name
        }
    }
    """

    result = _run_query(query)

    boards = result["data"]["boards"]

    return [
        {
            "board_id": b["id"],
            "board_name": b["name"]
        }
        for b in boards
    ]


# -------------------------------------------------
# 2. List items from board
# -------------------------------------------------

def list_items(board_id: int):
    """
    Returns items and ids from a board.
    """

    query = """
    query ($board_id: ID!) {
        boards(ids: [$board_id]) {
            items_page {
                items {
                    id
                    name
                }
            }
        }
    }
    """

    variables = {"board_id": board_id}

    result = _run_query(query, variables)

    items = result["data"]["boards"][0]["items_page"]["items"]

    return [
        {
            "item_id": i["id"],
            "item_name": i["name"]
        }
        for i in items
    ]


# -------------------------------------------------
# 3. List updates from item
# -------------------------------------------------

def list_updates(item_id: int):
    """
    Returns updates from an item.
    """

    query = """
    query ($item_id: ID!) {
        items(ids: [$item_id]) {
            id
            name
            updates {
                id
                body
                created_at
            }
        }
    }
    """

    variables = {"item_id": item_id}

    result = _run_query(query, variables)

    updates = result["data"]["items"][0]["updates"]

    return [
        {
            "update_id": u["id"],
            "text": u["body"],
            "created_at": u["created_at"]
        }
        for u in updates
    ]


# -------------------------------------------------
# 4. Add update to item
# -------------------------------------------------

import json

def add_update(
    item_id: int,
    text: str,
    board_id: int | None = None,
    status_label: str | None = None,
    status_column_id: str = "project_status"
):
    """
    Adds an update to an item and optionally updates the status column.

    Args:
        item_id: Monday item ID
        text: update text
        board_id: required if status will be updated
        status_label: label of the status (e.g. "Done", "Working on it")
        status_column_id: column id of the status field (default "status")
    """

    # If status update is requested
    if status_label and board_id:

        query = """
        mutation ($item_id: ID!, $body: String!, $board_id: ID!, $column_id: String!, $value: JSON!) {
            create_update(
                item_id: $item_id,
                body: $body
            ) {
                id
            }

            change_column_value(
                item_id: $item_id,
                board_id: $board_id,
                column_id: $column_id,
                value: $value
            ) {
                id
            }
        }
        """

        variables = {
            "item_id": item_id,
            "body": text,
            "board_id": board_id,
            "column_id": status_column_id,
            "value": json.dumps({"label": status_label})
        }

    else:

        query = """
        mutation ($item_id: ID!, $body: String!) {
            create_update(
                item_id: $item_id,
                body: $body
            ) {
                id
            }
        }
        """

        variables = {
            "item_id": item_id,
            "body": text
        }

    result = _run_query(query, variables)

    return result["data"]