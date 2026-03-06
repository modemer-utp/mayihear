"""
One-time setup: creates the Proyectos board, the Acta column, and the 3 project items in Monday.com.
Run from mayihear-api/ directory with the .env loaded.
"""
import os, json, requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("MONDAY_API_TOKEN")
URL   = "https://api.monday.com/v2"

PROJECTS = ["Evaluacion Recurrente", "Contenido adaptativo", "Personalizacion"]
COLUMN_TITLE = "Acta/resumen Ultima reunion"
BOARD_NAME   = "Proyectos"


def gql(query, variables=None):
    resp = requests.post(
        URL,
        json={"query": query, **({"variables": variables} if variables else {})},
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"][0]["message"])
    return data["data"]


def main():
    # 1. Create board
    print(f'Creating board "{BOARD_NAME}"...')
    board_id = gql(
        'mutation($n:String!){create_board(board_name:$n,board_kind:public){id}}',
        {"n": BOARD_NAME}
    )["create_board"]["id"]
    print(f"  Board ID: {board_id}")

    # 2. Create long_text column
    print(f'Creating column "{COLUMN_TITLE}"...')
    column_id = gql(
        'mutation($b:ID!,$t:String!){create_column(board_id:$b,title:$t,column_type:long_text){id}}',
        {"b": board_id, "t": COLUMN_TITLE}
    )["create_column"]["id"]
    print(f"  Column ID: {column_id}")

    # 3. Create project items
    for name in PROJECTS:
        print(f'Creating item "{name}"...')
        item_id = gql(
            'mutation($b:ID!,$n:String!){create_item(board_id:$b,item_name:$n){id}}',
            {"b": board_id, "n": name}
        )["create_item"]["id"]
        print(f"  Item ID: {item_id}")

    print("\n=== Add these to your .env ===")
    print(f"MONDAY_BOARD_ID={board_id}")
    print(f"MONDAY_COLUMN_ID={column_id}")


if __name__ == "__main__":
    main()
