# Monday Q&A — Resultados de Prueba

**Fecha:** 2026-03-31
**Board de prueba:** `fd` (ID: 18405594787) — 7 items, 2 grupos, 5 columnas
**Pregunta de prueba:** *¿qué tareas están bloqueadas y cuál es la razón?*

---

## Enfoques probados

### A — Text-to-GraphQL
Gemini lee el schema → genera un query GraphQL → lo ejecutamos → Gemini formatea la respuesta.

**Resultado:** ❌ Falló
**Razón:** El filtro por columna de status con `any_of` y valor `"Bloqueado"` devolvió 0 resultados. Los valores exactos del status en Monday son sensibles (índice interno, no texto libre). Además, si el concepto de "bloqueado" está en un grupo y no en una columna de status, la query generada es estructuralmente incorrecta.
**Tiempo:** 8.6s (3 llamadas: generate query → execute → format)

### B — Fetch-all + LLM ✅ ELEGIDO
Trae todos los items del tablero → los pasa como JSON al contexto de Gemini → Gemini razona sobre ellos.

**Resultado:** ✅ Funcionó
**Respuesta:**
> Solo una tarea se encuentra en estado de bloqueo: **Tarea 3** — Estado: Detenido — Fecha: 2026-03-27 — La razón específica no se detalla, solo su estado de "Detenido".

**Tiempo:** 4.5s
**Tokens:** ~1490 (7 items). Escala linealmente con el tamaño del tablero.

### C — Hybrid (plan → fetch dirigido)
Gemini lee schema → decide estrategia JSON → fetch dirigido → respuesta.

**Resultado:** ❌ Falló (misma causa que A)
**Razón:** Eligió `column_filter` con `project_status = "Bloqueado"`, que retornó 0 items.
**Tiempo:** 5.7s

---

## Decisión

**Usar Approach B** para la implementación actual.

**Por qué:**
- Funciona sin depender de valores exactos de status ni IDs de columnas
- Robusto ante cambios de estructura del tablero
- Rápido para tableros pequeños/medianos (<500 items)
- Simple de mantener

**Limitaciones conocidas:**
- Tokens escalan con el tamaño del board (~4 tokens por carácter de JSON)
- Para tableros grandes (>500 items) puede ser costoso o exceder el contexto
- No filtra: siempre trae todo aunque la pregunta sea específica

---

## Roadmap para cuando el tablero crezca

| Tamaño del board | Estrategia recomendada |
|---|---|
| < 500 items | **Approach B** (actual) — fetch-all + LLM |
| 500–2000 items | **Approach C mejorado** — fix status value mapping, usar grupos como pre-filtro |
| > 2000 items | **RAG** — sync periódico a Azure Table Storage / Azure AI Search |

### Fix pendiente para A y C
El problema raíz: Monday status columns usan **índices numéricos** internamente, no texto libre.
Para filtrar por status correctamente hay que primero obtener el mapa de labels:
```graphql
columns(ids: ["project_status"]) { settings_str }  # JSON con {"labels": {"1": "En progreso", "2": "Detenido"}}
```
Luego buscar el índice que corresponde a "Bloqueado" / "Detenido" y filtrar por índice.
Esto hace Approach A/C viable pero requiere un paso extra de schema lookup.

---

## Implementación actual (bot.py)

El bot detecta preguntas sobre Monday con `_is_monday_question()`:
- Señales de pregunta: `?`, `¿`, `qué`, `cuál`, `quién`, `cuándo`, `cuánto`, etc.
- Palabras clave Monday: `tarea`, `pendiente`, `decisión`, `insights`, `proyecto`, etc.

Si ambas condiciones se cumplen → llama a `tools/monday_qa.py::ask_monday()` con Approach B.

**Ejemplos que funcionan en Teams:**
- *¿qué tareas quedaron pendientes?*
- *¿quién tiene más tareas asignadas?*
- *¿cuáles son las decisiones más recientes?*
- *dame un resumen del estado del proyecto*
