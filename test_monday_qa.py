"""
Monday Q&A — three-approach comparison.

Run from project root:
    python test_monday_qa.py
    python test_monday_qa.py "¿qué tareas están bloqueadas?"

Approaches:
  A. Text-to-GraphQL (schema-aware): Gemini sees real column IDs + group IDs → generates query → execute → format
  B. Fetch-all + LLM:                Fetch all items as JSON → dump into Gemini context → Gemini reasons
  C. Hybrid (smart):                 Gemini reads schema → decides filter strategy → targeted fetch → format
                                     Best of both: precise like A, robust like B, efficient tokens
"""
import os
import sys
import json
import time
import re
import requests
from dotenv import load_dotenv
from google import genai

load_dotenv("teams-agent/.env.dev")

MONDAY_API   = "https://api.monday.com/v2"
BOARD_ID     = os.environ.get("MONDAY_BOARD_ID", "18405594787")
GEMINI_KEY   = os.environ["GEMINI_API_KEY"]
MONDAY_TOKEN = os.environ["MONDAY_TOKEN"]
GEMINI_MODEL = "gemini-2.5-flash"

_client = None
def _gemini():
    global _client
    if not _client:
        _client = genai.Client(api_key=GEMINI_KEY)
    return _client

def _h():
    return {
        "Authorization": f"Bearer {MONDAY_TOKEN}",
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }

def gql(query: str, variables: dict = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    r = requests.post(MONDAY_API, json=payload, headers=_h(), timeout=20)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data.get("data", {})


# ══════════════════════════════════════════════════════════════════════════════
# Schema — fetched once, shared across all approaches
# ══════════════════════════════════════════════════════════════════════════════

def fetch_schema(board_id: str) -> dict:
    """Returns {name, board_id, columns: [{id,title,type}], groups: [{id,title}]}"""
    data = gql("""
    query($bid: ID!) {
      boards(ids: [$bid]) {
        name
        columns { id title type }
        groups   { id title }
      }
    }
    """, {"bid": board_id})
    b = data["boards"][0]
    return {
        "name":     b["name"],
        "board_id": board_id,
        "columns":  b["columns"],
        "groups":   b["groups"],
    }


def schema_to_text(s: dict) -> str:
    lines = [f'Board: "{s["name"]}"  (ID: {s["board_id"]})']
    lines.append("\nColumnas disponibles (usa el 'id' exacto en las queries):")
    for c in s["columns"]:
        lines.append(f"  id={c['id']!r:30s}  title={c['title']!r:25s}  type={c['type']}")
    lines.append("\nGrupos disponibles (usa el 'id' exacto para filtrar por grupo):")
    for g in s["groups"]:
        lines.append(f"  id={g['id']!r:20s}  title={g['title']!r}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# APPROACH A — Text-to-GraphQL (schema-aware, group-aware)
# ══════════════════════════════════════════════════════════════════════════════

_PROMPT_A_GENERATE = """\
You are a Monday.com GraphQL v2 expert. Generate a valid query to answer the user's question.

{schema}

== MONDAY GRAPHQL RULES (read carefully) ==

1. Filter by GROUP (use this when question is about a group like "bloqueado", "pendiente", "completado"):
   boards(ids: [{board_id}]) {{
     groups(ids: ["GROUP_ID_HERE"]) {{
       title
       items_page(limit: 50) {{
         items {{ id name column_values {{ id text }} }}
       }}
     }}
   }}

2. Filter by COLUMN VALUE (use for status, assignee, priority filters):
   boards(ids: [{board_id}]) {{
     items_page(limit: 50, query_params: {{
       rules: [{{ column_id: "EXACT_COLUMN_ID", compare_value: ["value"], operator: OPERATOR }}]
     }}) {{
       items {{ id name column_values {{ id text }} }}
     }}
   }}
   Operators by column type:
   - status / priority columns  → use: any_of
   - text / long_text columns   → use: contains_text
   - date columns               → use: greater_than or lower_than with "YYYY-MM-DD"
   - people columns             → use: any_of (compare_value is the person's name text)

3. Fetch ALL items (use when question is broad / analytical):
   boards(ids: [{board_id}]) {{
     items_page(limit: 200) {{
       items {{ id name column_values {{ id text }} }}
     }}
   }}

4. Always use the EXACT column id and group id from the schema above.
5. Select column_values {{ id text }} to get readable values.

== USER QUESTION ==
{question}

Return ONLY the GraphQL query. No explanation, no markdown, no comments. Start with 'query'.
"""

_PROMPT_A_FORMAT = """\
El usuario preguntó: {question}

Datos devueltos por Monday.com:
{data}

Responde en español, de forma clara y concisa.
Si hay tareas o elementos, enuméralos con viñetas e incluye el responsable y fecha si están disponibles.
Si no hay datos, dilo claramente.
"""


def approach_a(question: str, schema: dict) -> tuple[str, str, float]:
    """Returns (answer, generated_query, elapsed)"""
    t0 = time.time()
    schema_text = schema_to_text(schema)

    print("  [A1] Gemini generando query GraphQL...")
    raw = _gemini().models.generate_content(
        model=GEMINI_MODEL,
        contents=_PROMPT_A_GENERATE.format(
            schema=schema_text,
            board_id=schema["board_id"],
            question=question,
        ),
    ).text.strip()

    # Strip markdown fences if Gemini added them
    raw = re.sub(r"^```\w*\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE).strip()

    print("  [A2] Ejecutando query en Monday API...")
    try:
        result = gql(raw)
        data_str = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        data_str = f"Error ejecutando query: {e}"

    print("  [A3] Gemini formateando respuesta...")
    answer = _gemini().models.generate_content(
        model=GEMINI_MODEL,
        contents=_PROMPT_A_FORMAT.format(question=question, data=data_str),
    ).text.strip()

    return answer, raw, time.time() - t0


# ══════════════════════════════════════════════════════════════════════════════
# APPROACH B — Fetch-all + LLM
# ══════════════════════════════════════════════════════════════════════════════

_PROMPT_B = """\
Eres un asistente de productividad. Responde en español, de forma concisa y directa.
Basa tu respuesta ÚNICAMENTE en los datos del tablero de Monday que se muestran abajo.

== DATOS DEL TABLERO "{board_name}" ==
{board_data}
== FIN DATOS ==

Pregunta: {question}

Responde con claridad. Enumera tareas con viñetas. Si hay responsable o fecha, inclúyelos.
No inventes información que no esté en los datos.
"""


def fetch_all_items(board_id: str) -> list:
    data = gql("""
    query($bid: ID!) {
      boards(ids: [$bid]) {
        items_page(limit: 200) {
          items {
            id name state
            group { title }
            column_values { id text }
          }
        }
      }
    }
    """, {"bid": board_id})
    return data["boards"][0]["items_page"]["items"]


def approach_b(question: str, board_name: str) -> tuple[str, int, float]:
    """Returns (answer, item_count, elapsed)"""
    t0 = time.time()

    print("  [B1] Obteniendo todos los items de Monday...")
    items = fetch_all_items(BOARD_ID)

    compact = []
    for item in items:
        cols = {cv["id"]: cv["text"] for cv in item.get("column_values", []) if cv.get("text")}
        compact.append({
            "id":    item["id"],
            "name":  item["name"],
            "grupo": item.get("group", {}).get("title", ""),
            **cols,
        })

    board_str = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
    tokens = len(board_str) // 4
    print(f"  [B2] Enviando {len(items)} items (~{tokens} tokens) a Gemini...")

    answer = _gemini().models.generate_content(
        model=GEMINI_MODEL,
        contents=_PROMPT_B.format(
            board_name=board_name,
            board_data=board_str,
            question=question,
        ),
    ).text.strip()

    return answer, len(items), time.time() - t0


# ══════════════════════════════════════════════════════════════════════════════
# APPROACH C — Hybrid: Gemini plans the query, targeted fetch, then answers
#
# Step 1: Gemini reads schema + question → returns a JSON "fetch plan"
#         {strategy: "group"|"column_filter"|"fetch_all",
#          group_ids: [...], column_id: "...", compare_value: "..."}
# Step 2: Execute targeted fetch based on plan (only relevant items)
# Step 3: Gemini answers with the filtered data
#
# Best of both worlds: precise targeting (reduces tokens) + no hallucinated IDs
# ══════════════════════════════════════════════════════════════════════════════

_PROMPT_C_PLAN = """\
You are a Monday.com query planner. Given the board schema and user question,
decide the most efficient fetch strategy.

{schema}

== USER QUESTION ==
{question}

== OUTPUT FORMAT ==
Return ONLY a JSON object (no markdown), exactly one of these shapes:

If the question is about a specific group (pendiente, bloqueado, completado, en progreso):
{{"strategy": "group", "group_ids": ["ID1", "ID2"], "reason": "brief"}}

If the question filters by a column value (status, assignee, priority, date range):
{{"strategy": "column_filter", "column_id": "EXACT_ID", "compare_value": "value", "operator": "OPERATOR", "reason": "brief"}}
Operators: status/priority → any_of | text/long_text → contains_text | date → greater_than or lower_than

If the question is broad/analytical (counts, comparisons, trends, all items):
{{"strategy": "fetch_all", "reason": "brief"}}

Use exact IDs from the schema. Return only the JSON.
"""

_PROMPT_C_ANSWER = """\
Eres un asistente de productividad. Responde en español, claro y conciso.

Tablero: "{board_name}"
Datos obtenidos para responder la pregunta:
{data}

Pregunta: {question}

Enumera con viñetas si hay tareas. Incluye responsable y fecha si están disponibles.
No inventes información que no esté en los datos.
"""


def _fetch_by_groups(board_id: str, group_ids: list) -> list:
    ids_str = json.dumps(group_ids)
    data = gql(f"""
    query {{
      boards(ids: [{board_id}]) {{
        groups(ids: {ids_str}) {{
          title
          items_page(limit: 100) {{
            items {{ id name column_values {{ id text }} }}
          }}
        }}
      }}
    }}
    """)
    items = []
    for group in data["boards"][0]["groups"]:
        for item in group["items_page"]["items"]:
            item["_group"] = group["title"]
            items.append(item)
    return items


def _fetch_by_column(board_id: str, column_id: str, compare_value: str, operator: str) -> list:
    # Build query as string — avoids GraphQL variable type mismatches with Monday's schema
    query = f"""
    query {{
      boards(ids: [{board_id}]) {{
        items_page(limit: 100, query_params: {{
          rules: [{{ column_id: "{column_id}", compare_value: ["{compare_value}"], operator: {operator} }}]
        }}) {{
          items {{ id name column_values {{ id text }} }}
        }}
      }}
    }}
    """
    data = gql(query)
    return data["boards"][0]["items_page"]["items"]


def approach_c(question: str, schema: dict) -> tuple[str, dict, float]:
    """Returns (answer, plan, elapsed)"""
    t0 = time.time()
    schema_text = schema_to_text(schema)

    print("  [C1] Gemini planificando estrategia de fetch...")
    raw_plan = _gemini().models.generate_content(
        model=GEMINI_MODEL,
        contents=_PROMPT_C_PLAN.format(schema=schema_text, question=question),
    ).text.strip()

    # Strip markdown if present
    raw_plan = re.sub(r"^```\w*\s*", "", raw_plan, flags=re.MULTILINE)
    raw_plan = re.sub(r"```\s*$", "", raw_plan, flags=re.MULTILINE).strip()

    try:
        plan = json.loads(raw_plan)
    except Exception:
        print(f"  [C!] Plan parse failed, fallback to fetch_all. Raw: {raw_plan[:200]}")
        plan = {"strategy": "fetch_all", "reason": "parse error"}

    strategy = plan.get("strategy", "fetch_all")
    print(f"  [C2] Estrategia: {strategy} — {plan.get('reason', '')}")

    if strategy == "group":
        group_ids = plan.get("group_ids", [])
        print(f"  [C3] Fetching grupos {group_ids}...")
        items = _fetch_by_groups(BOARD_ID, group_ids)

    elif strategy == "column_filter":
        col_id  = plan.get("column_id", "")
        val     = plan.get("compare_value", "")
        op      = plan.get("operator", "contains_text")
        print(f"  [C3] Fetching por columna {col_id!r}={val!r}...")
        items = _fetch_by_column(BOARD_ID, col_id, val, op)

    else:  # fetch_all
        print("  [C3] Fetching todos los items...")
        items = fetch_all_items(BOARD_ID)

    compact = []
    for item in items:
        cols = {cv["id"]: cv["text"] for cv in item.get("column_values", []) if cv.get("text")}
        compact.append({
            "name":  item["name"],
            "grupo": item.get("_group") or item.get("group", {}).get("title", ""),
            **cols,
        })

    tokens = len(json.dumps(compact)) // 4
    print(f"  [C4] Gemini respondiendo ({len(items)} items, ~{tokens} tokens)...")

    answer = _gemini().models.generate_content(
        model=GEMINI_MODEL,
        contents=_PROMPT_C_ANSWER.format(
            board_name=schema["name"],
            data=json.dumps(compact, ensure_ascii=False, separators=(",", ":")),
            question=question,
        ),
    ).text.strip()

    return answer, plan, time.time() - t0


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def run_test(question: str, schema: dict):
    sep = "─" * 72
    print(f"\n{sep}")
    print(f"PREGUNTA: {question}")
    print(sep)

    results = {}

    print("\n▶ APPROACH A — Text-to-GraphQL (schema-aware):")
    try:
        ans_a, query_a, t_a = approach_a(question, schema)
        print(f"\n  Query generada:\n  {'·'*50}")
        for line in query_a.splitlines():
            print(f"    {line}")
        print(f"  {'·'*50}")
        print(f"\n  Respuesta ({t_a:.1f}s):\n  {ans_a}")
        results["A"] = t_a
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results["A"] = None

    print(f"\n▶ APPROACH B — Fetch-all + LLM:")
    try:
        ans_b, count_b, t_b = approach_b(question, schema["name"])
        print(f"\n  Respuesta ({t_b:.1f}s, {count_b} items):\n  {ans_b}")
        results["B"] = t_b
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results["B"] = None

    print(f"\n▶ APPROACH C — Hybrid (plan → targeted fetch):")
    try:
        ans_c, plan_c, t_c = approach_c(question, schema)
        print(f"\n  Plan: {plan_c}")
        print(f"\n  Respuesta ({t_c:.1f}s):\n  {ans_c}")
        results["C"] = t_c
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        results["C"] = None

    ta = f"{results['A']:.1f}s" if results.get('A') else "ERR"
    tb = f"{results['B']:.1f}s" if results.get('B') else "ERR"
    tc = f"{results['C']:.1f}s" if results.get('C') else "ERR"
    print(f"\n  ⏱  A: {ta}  |  B: {tb}  |  C: {tc}")


QUESTIONS = [
    "¿Qué tareas están bloqueadas y cuál es la razón?",
    "¿Qué tareas están en progreso?",
    "¿Cuáles tareas completó Carlos Mendoza?",
    "¿Qué tiene mayor prioridad esta semana?",
    "¿Cuántas tareas tiene cada responsable?",
]


def main():
    print("=== Monday Q&A — Comparación de Enfoques (A / B / C) ===")
    print(f"Board ID: {BOARD_ID}\n")

    print("Obteniendo schema del tablero...")
    try:
        schema = fetch_schema(BOARD_ID)
        print(f"Tablero: {schema['name']} | {len(schema['columns'])} columnas | {len(schema['groups'])} grupos")
        print(schema_to_text(schema))
    except Exception as e:
        print(f"❌ No se pudo obtener el schema: {e}")
        sys.exit(1)

    if len(sys.argv) > 1:
        run_test(" ".join(sys.argv[1:]), schema)
    else:
        for q in QUESTIONS[:2]:
            run_test(q, schema)
            time.sleep(1)

    print("\n=== Fin ===")


if __name__ == "__main__":
    main()
