"""
Explore all Monday.com boards in the workspace.
Lists boards with id, name, item count, and description.
"""
import requests
import json

MONDAY_API_URL = "https://api.monday.com/v2"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjY0MjYzNDE2NiwiYWFpIjoxMSwidWlkIjo5ODc2MTgxNCwiaWFkIjoiMjAyNi0wNC0wN1QxNzoyMjowOS44MDdaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6NDcxNzc4OSwicmduIjoidXNlMSJ9.O5oflE6wv84DklhG3n6kISRGkgA5T731g7xIR1wCP6A"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "API-Version": "2024-01",
}


def gql(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(MONDAY_API_URL, json=payload, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday.com error: {data['errors']}")
    return data["data"]


def get_all_boards():
    """Fetch all boards with pagination."""
    all_boards = []
    page = 1
    while True:
        query = f"""
        {{
          boards(limit: 50, page: {page}, order_by: used_at) {{
            id
            name
            description
            state
            items_count
            workspace {{
              id
              name
            }}
            type
            updated_at
          }}
        }}
        """
        data = gql(query)
        boards = data.get("boards", [])
        if not boards:
            break
        all_boards.extend(boards)
        if len(boards) < 50:
            break
        page += 1
    return all_boards


def get_board_groups(board_id):
    query = """
    query($ids: [ID!]!) {
      boards(ids: $ids) {
        groups { id title color }
        columns { id title type }
      }
    }
    """
    try:
        data = gql(query, {"ids": [board_id]})
        b = data["boards"][0]
        return b.get("groups", []), b.get("columns", [])
    except Exception as e:
        return [], []


if __name__ == "__main__":
    print("Fetching all boards from Monday.com workspace...\n")
    boards = get_all_boards()

    print(f"Total boards found: {len(boards)}\n")
    print("=" * 80)

    # Filter out boards that are likely deleted/archived
    active_boards = [b for b in boards if b.get("state") != "deleted"]

    for b in active_boards:
        workspace = b.get("workspace") or {}
        print(f"Board: {b['name']}")
        print(f"  ID         : {b['id']}")
        print(f"  State      : {b.get('state', 'unknown')}")
        print(f"  Type       : {b.get('type', 'unknown')}")
        print(f"  Items      : {b.get('items_count', 0)}")
        print(f"  Workspace  : {workspace.get('name', 'N/A')} (id: {workspace.get('id', 'N/A')})")
        print(f"  Updated at : {b.get('updated_at', 'N/A')}")
        if b.get("description"):
            print(f"  Description: {b['description'][:120]}")
        print()

    # Save full data to JSON for review
    with open("monday_boards_export.json", "w", encoding="utf-8") as f:
        json.dump(active_boards, f, ensure_ascii=False, indent=2)
    print(f"\nFull data saved to monday_boards_export.json")
