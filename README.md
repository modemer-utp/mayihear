# MayiHear

Meeting transcription and insights tool for UTP directors and high-rank employees. Captures system audio, transcribes it, and extracts structured summaries, decisions, and action items.UTP

---

## 1. Lenguajes y Frameworks

| Capa | Lenguaje | Framework / Librería |
|---|---|---|
| Desktop app | JavaScript (Node.js) | Electron 33 |
| Backend API | Python 3.x | FastAPI 0.115, Uvicorn 0.30 |
| Agentes IA | Python 3.x | LangChain 0.3, LangGraph 0.2 |
| Modelos de datos | Python 3.x | Pydantic 2.x |

---

## 2. Infraestructura

| Componente | Dónde corre |
|---|---|
| Desktop app | Local — Windows (Electron) |
| Backend API | Local — `localhost:8000` (FastAPI + Uvicorn) |
| Almacenamiento temporal de audio | Google Gemini File API (durante transcripción) |

MVP totalmente local. No hay cloud deployment ni servidores propios. El audio nunca sale del equipo salvo el fragmento enviado a las APIs de IA.

---

## 3. Datos y Almacenamiento

| Dato | Almacenamiento |
|---|---|
| Audio grabado | En memoria / archivo temporal local (eliminado tras la transcripción) |
| Transcripción | En memoria — devuelta al frontend, no persistida |
| Insights generados | En memoria — devuelta al frontend, no persistida |
| API keys | `.env` local (no commiteado) |

No hay base de datos en el MVP. Todo es stateless por request.

---

## 4. AI — Modelos y Proveedores

| Tarea | Modelo | Proveedor | SDK |
|---|---|---|---|
| Transcripción de audio | `gemini-2.5-pro` (fallback: `gemini-2.0-flash`) | Google Gemini | `google-genai` |
| Generación de insights | `gemini-2.5-flash` (opt: `gemini-2.5-pro`) | Google Gemini | LangChain + `langchain-google-genai` |

**Orquestación de agentes:** LangGraph `StateGraph` (TypedDict states).

Credenciales configuradas también para OpenAI y Anthropic (uso futuro).

---

## 5. Métricas y Monitoreo

No hay sistema de métricas en el MVP.

| Herramienta | Uso actual |
|---|---|
| Uvicorn logs | Logs de requests HTTP en consola |
| `/health` endpoint | Health check básico (`GET localhost:8000/health`) |

---

## 6. Herramientas de Desarrollo y Repositorios

| Herramienta | Uso |
|---|---|
| Git | Control de versiones |
| VS Code | IDE principal |
| Anaconda | Gestión del entorno Python |
| `python-dotenv` | Carga de variables de entorno desde `.env` |
| `.env.example` | Plantilla de configuración de API keys |

### Estructura del proyecto

```
project_mayihear/
├── main.js                  # Electron entry point
├── preload.js               # Electron preload bridge
├── renderer/                # Frontend (HTML/CSS/JS)
├── mayihear-api/            # Python FastAPI backend
│   ├── api/                 # Controllers + main app
│   ├── application/         # Services + handlers
│   ├── agents/              # LangGraph agents + prompts
│   ├── domain/              # Pydantic models (input/output)
│   └── infrastructure/      # Secret manager, utilities
└── package.json
```
