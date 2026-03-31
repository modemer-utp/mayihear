"""
Crea un tablero de prueba en Monday.com con datos del proyecto MayiHear UTP.
Columnas, grupos y tareas en español — listos para probar el Q&A del agente.

Uso:
    python setup_monday_test_board.py

Al finalizar imprime el BOARD_ID para agregar a teams-agent/.env.dev:
    MONDAY_BOARD_ID=<id>
"""
import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv("teams-agent/.env.dev")

MONDAY_API   = "https://api.monday.com/v2"
MONDAY_TOKEN = os.environ["MONDAY_TOKEN"]


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
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]


# ── 1. Crear tablero ──────────────────────────────────────────────────────────

def create_board(name: str) -> str:
    data = gql("""
    mutation($name: String!) {
      create_board(board_name: $name, board_kind: public) { id }
    }
    """, {"name": name})
    board_id = data["create_board"]["id"]
    print(f"[OK] Tablero creado: '{name}' → id={board_id}")
    return board_id


# ── 2. Crear columnas ─────────────────────────────────────────────────────────

def create_column(board_id: str, title: str, col_type: str) -> str:
    data = gql("""
    mutation($board_id: ID!, $title: String!, $col_type: ColumnType!) {
      create_column(board_id: $board_id, title: $title, column_type: $col_type) { id }
    }
    """, {"board_id": board_id, "title": title, "col_type": col_type})
    col_id = data["create_column"]["id"]
    print(f"  [col] {title!r} ({col_type}) → {col_id}")
    return col_id


# ── 3. Crear grupos ───────────────────────────────────────────────────────────

def create_group(board_id: str, name: str) -> str:
    data = gql("""
    mutation($board_id: ID!, $name: String!) {
      create_group(board_id: $board_id, group_name: $name) { id }
    }
    """, {"board_id": board_id, "name": name})
    group_id = data["create_group"]["id"]
    print(f"  [grp] {name!r} → {group_id}")
    return group_id


# ── 4. Crear ítem con valores de columna ──────────────────────────────────────

def create_item(board_id: str, group_id: str, name: str, col_values: dict) -> str:
    col_values_json = json.dumps(col_values)
    data = gql("""
    mutation($board_id: ID!, $group_id: String!, $name: String!, $cv: JSON!) {
      create_item(board_id: $board_id, group_id: $group_id, item_name: $name, column_values: $cv) { id }
    }
    """, {
        "board_id": board_id,
        "group_id": group_id,
        "name": name,
        "cv": col_values_json,
    })
    item_id = data["create_item"]["id"]
    print(f"    [item] {name!r} → {item_id}")
    return item_id


# ── 5. Renombrar grupo por defecto ────────────────────────────────────────────

def get_default_group(board_id: str) -> str:
    """Monday crea un grupo por defecto 'Topics'. Lo renombramos."""
    data = gql("""
    query($board_id: ID!) {
      boards(ids: [$board_id]) { groups { id title } }
    }
    """, {"board_id": board_id})
    groups = data["boards"][0]["groups"]
    return groups[0]["id"] if groups else None


def rename_group(board_id: str, group_id: str, new_name: str):
    gql("""
    mutation($board_id: ID!, $group_id: String!, $name: String!) {
      update_group(board_id: $board_id, group_id: $group_id, attribute: title, new_value: $name) { id }
    }
    """, {"board_id": board_id, "group_id": group_id, "name": new_name})
    print(f"  [grp] Grupo por defecto renombrado → '{new_name}'")


# ═════════════════════════════════════════════════════════════════════════════
# DATOS DEL PROYECTO — simulación realista de UTP / MayiHear
# ═════════════════════════════════════════════════════════════════════════════

TASKS = {
    "En Progreso": [
        {
            "name": "Implementar webhook de transcripción Graph API",
            "responsable": "Carlos Mendoza",
            "prioridad": "Alta",
            "fecha": "2026-04-05",
            "descripcion": "Configurar suscripción a cambios de transcripción en Teams via Graph API. Ya funciona el poller como fallback.",
            "notas": "El webhook necesita lifecycleNotificationUrl. Pendiente verificar que las notificaciones lleguen correctamente.",
        },
        {
            "name": "Integrar Monday Q&A con el agente de Teams",
            "responsable": "Ana Ríos",
            "prioridad": "Alta",
            "fecha": "2026-04-10",
            "descripcion": "Permitir que el bot responda preguntas sobre el tablero de Monday usando Gemini.",
            "notas": "Probando dos enfoques: Text-to-GraphQL vs Fetch-all + LLM. En test esta semana.",
        },
        {
            "name": "Ruteo multi-usuario de notificaciones proactivas",
            "responsable": "Carlos Mendoza",
            "prioridad": "Media",
            "fecha": "2026-04-08",
            "descripcion": "Actualmente _get_any_ref() devuelve el primer ref guardado sin importar quién organizó la reunión.",
            "notas": "Solución documentada en MULTI_USER_ROUTING.md. Implementación en curso.",
        },
    ],
    "Pendiente": [
        {
            "name": "Implementar generación automática de Acta de Reunión",
            "responsable": "Laura Torres",
            "prioridad": "Media",
            "fecha": "2026-04-20",
            "descripcion": "Agregar comando 'acta' al bot para generar documento Word con formato institucional UTP.",
            "notas": "Requiere definir plantilla con Legal. Pendiente aprobación de formato.",
        },
        {
            "name": "Soporte para múltiples organizadores (ORGANIZER_EMAILS)",
            "responsable": "Ana Ríos",
            "prioridad": "Media",
            "fecha": "2026-04-15",
            "descripcion": "Escalar de un solo organizador a múltiples via variable de entorno comma-separated.",
            "notas": "Código listo, falta deploy y prueba con segundo usuario de prueba.",
        },
        {
            "name": "Implementar RAG con Azure AI Search para historial",
            "responsable": "Carlos Mendoza",
            "prioridad": "Baja",
            "fecha": "2026-05-15",
            "descripcion": "Indexar items históricos de Monday en vector DB para responder preguntas sobre tendencias.",
            "notas": "Evaluar si fetch-all + LLM es suficiente primero. Costo Azure AI Search ~$25/mes.",
        },
        {
            "name": "Pruebas de carga: 10 reuniones simultáneas",
            "responsable": "Luis Vargas",
            "prioridad": "Media",
            "fecha": "2026-04-30",
            "descripcion": "Verificar que Service Bus + Azure Functions escala correctamente con múltiples reuniones concurrentes.",
            "notas": "Service Bus Basic soporta hasta 256KB por mensaje. Verificar tamaño de transcripciones largas.",
        },
        {
            "name": "Dashboard de métricas en Azure Monitor",
            "responsable": "Laura Torres",
            "prioridad": "Baja",
            "fecha": "2026-05-10",
            "descripcion": "Crear dashboard con: reuniones procesadas por día, tiempo promedio de procesamiento, errores.",
            "notas": "Datos ya disponibles en Application Insights. Solo falta el dashboard visual.",
        },
    ],
    "Completado": [
        {
            "name": "Despliegue en Azure Functions (Solution B)",
            "responsable": "Carlos Mendoza",
            "prioridad": "Alta",
            "fecha": "2026-03-20",
            "descripcion": "Migración de Lambda AWS (Solution A) a Azure Functions para mejor integración con Teams.",
            "notas": "Desplegado y en producción. Poller funciona cada 5 min. Bot activo en Teams.",
        },
        {
            "name": "Integración con Monday.com para publicar insights",
            "responsable": "Ana Ríos",
            "prioridad": "Alta",
            "fecha": "2026-03-15",
            "descripcion": "Bot genera insights con Gemini y publica en Monday tras confirmación del usuario.",
            "notas": "Funcionando. Usuario confirma/regenera/cancela antes de publicar.",
        },
        {
            "name": "Persistencia de estado en Azure Table Storage",
            "responsable": "Carlos Mendoza",
            "prioridad": "Alta",
            "fecha": "2026-03-22",
            "descripcion": "Reemplazar dict en memoria por Azure Table Storage para sobrevivir reinicios.",
            "notas": "Completado. Estado de conversación persiste entre redeploys e instancias múltiples.",
        },
        {
            "name": "Cola de reuniones concurrentes (pending_queue)",
            "responsable": "Ana Ríos",
            "prioridad": "Media",
            "fecha": "2026-03-25",
            "descripcion": "Si el usuario está revisando una reunión y termina otra, se pone en cola automáticamente.",
            "notas": "Probado y funcionando. La segunda reunión aparece como 'en cola' hasta que termines la actual.",
        },
        {
            "name": "Service Bus para procesamiento asíncrono confiable",
            "responsable": "Luis Vargas",
            "prioridad": "Alta",
            "fecha": "2026-03-26",
            "descripcion": "Agregar Azure Service Bus para retry automático (10x) y Dead Letter Queue.",
            "notas": "Completado. Costo ~$0.01/mes en tier Basic.",
        },
        {
            "name": "Eliminar secretos hardcodeados del repositorio",
            "responsable": "Carlos Mendoza",
            "prioridad": "Crítica",
            "fecha": "2026-03-27",
            "descripcion": "GitHub bloqueó push por CLIENT_SECRET y BOT_PASSWORD hardcodeados en test_graph_api.py.",
            "notas": "Resuelto: movido a .env.dev (gitignored). Variables cargadas con python-dotenv.",
        },
    ],
    "Bloqueado": [
        {
            "name": "Acceso a transcripciones de llamadas ad-hoc",
            "responsable": "Luis Vargas",
            "prioridad": "Media",
            "fecha": "2026-04-25",
            "descripcion": "El endpoint /adhocCalls/getAllTranscripts requiere permisos adicionales de Teams Admin.",
            "notas": "Bloqueado por falta de licencia Teams Premium o política CsApplicationAccessPolicy. Pendiente gestión con IT.",
        },
        {
            "name": "Notificaciones webhook en tiempo real (Graph API)",
            "responsable": "Ana Ríos",
            "prioridad": "Alta",
            "fecha": "2026-04-12",
            "descripcion": "El webhook no dispara notificaciones reales, solo handshakes de validación.",
            "notas": "Posibles causas: (1) política de Teams no habilitada, (2) delay en propagación de suscripción. El poller cubre como fallback.",
        },
    ],
}


def main():
    print("=== Setup Tablero Monday — Proyecto MayiHear UTP ===\n")

    # Crear tablero
    board_id = create_board("MayiHear UTP — Gestión del Proyecto")
    time.sleep(1)

    # Renombrar grupo por defecto
    default_group = get_default_group(board_id)
    if default_group:
        rename_group(board_id, default_group, "En Progreso")

    # Crear columnas
    print("\nCreando columnas...")
    cols = {}
    cols["responsable"] = create_column(board_id, "Responsable",  "text")
    cols["prioridad"]   = create_column(board_id, "Prioridad",    "status")
    cols["fecha"]       = create_column(board_id, "Fecha límite", "date")
    cols["descripcion"] = create_column(board_id, "Descripción",  "long_text")
    cols["notas"]       = create_column(board_id, "Notas",        "long_text")
    time.sleep(1)

    # Crear grupos adicionales y tareas
    print("\nCreando grupos y tareas...")
    groups = {}

    for group_name, tasks in TASKS.items():
        if group_name == "En Progreso" and default_group:
            groups[group_name] = default_group
        else:
            groups[group_name] = create_group(board_id, group_name)
            time.sleep(0.5)

        print(f"\n  → Grupo '{group_name}' ({len(tasks)} tareas):")
        for task in tasks:
            cv = {
                cols["responsable"]: task["responsable"],
                cols["prioridad"]:   {"label": task["prioridad"]},
                cols["fecha"]:       {"date": task["fecha"]},
                cols["descripcion"]: {"text": task["descripcion"]},
                cols["notas"]:       {"text": task["notas"]},
            }
            create_item(board_id, groups[group_name], task["name"], cv)
            time.sleep(0.3)  # Respetar rate limit de Monday

    # Resultado
    total_tasks = sum(len(t) for t in TASKS.values())
    print(f"""
═══════════════════════════════════════════════════════════
✅ Tablero creado exitosamente

   Board ID : {board_id}
   Tareas   : {total_tasks} ({len(TASKS)} grupos)
   Columnas : Responsable, Prioridad, Fecha límite, Descripción, Notas

Agrega esto a teams-agent/.env.dev:
   MONDAY_BOARD_ID={board_id}

Luego prueba el Q&A:
   python test_monday_qa.py "¿qué tareas están pendientes?"
   python test_monday_qa.py "¿qué está bloqueado y por qué?"
   python test_monday_qa.py "¿cuáles tareas completó Carlos Mendoza?"
   python test_monday_qa.py "¿qué tiene mayor prioridad esta semana?"
═══════════════════════════════════════════════════════════
""")


if __name__ == "__main__":
    main()
