# MayiHear Teams Agent — Features & Architecture

## How the bot works (end-to-end flow)

```
Meeting ends
    ↓  (5–30 min) Teams processes transcript
Graph API → POST /api/webhook
    ↓
Fetch transcript (VTT) via Graph API
    ↓
Parse VTT → plain text
    ↓
Generate insights via Gemini 1.5 Flash
    ↓
Bot sends proactive message to organizer in Teams:
  "📝 Nueva reunión lista: [subject]
   [formatted insights]
   Responde: confirmar · regenerar · cancelar"
    ↓
User replies:
  confirmar  → publish to selected Monday board
  regenerar  → call Gemini again with same transcript, show new result
  cancelar   → discard
```

> **Important:** For the proactive message to work, the organizer must have sent at least
> one message to the bot after the last deploy. The bot stores the conversation reference
> in memory from incoming messages, and uses it to initiate outgoing ones.
> If no reference is stored → auto-posts to Monday as fallback.

---

## Bot commands

| Command | Description |
|---|---|
| `status` | Shows the agent is active |
| `boards` | Lists all Monday boards, lets user select one for publishing |
| `last meeting` | Shows insights + Monday item ID from the last processed meeting |
| (any other text) | Shows help with current board name |

---

## Insight confirmation flow (state machine)

When a meeting is processed, the bot enters `awaiting_confirmation` phase:

- **confirmar / sí / yes** → publishes to selected Monday board, shows item ID
- **regenerar** → calls Gemini again with the same transcript, shows new insights, asks again
- **cancelar / no** → discards, nothing posted to Monday

---

## Board selection flow

Type `boards` → bot lists all accessible Monday boards:
```
Tableros disponibles en Monday:
1. Insights EYA ✅   ← currently selected
2. Sprint Planning
3. Reuniones Q2
Responde con el número del tablero...
```
Reply with a number → saved for that conversation session.

---

## Monday item structure

Each processed meeting creates a Monday item:
- **Item name**: Teams meeting subject (e.g. "Reunión semanal de producto")
- **Insights column** (long text): formatted insights with sections:
  - 📋 RESUMEN
  - ✅ DECISIONES
  - 🎯 TAREAS
  - ❓ PREGUNTAS ABIERTAS

---

## Planned features (next)

- [ ] Meeting act / acta generation as separate command
- [ ] Per-user board preference (persisted across sessions)
- [ ] Multiple organizers supported
- [ ] Container Apps migration for reliable demo hosting

---

## Container Apps vs Azure Functions (hosting comparison)

| Feature | Functions Consumption (now) | Container Apps | VM B1s |
|---|---|---|---|
| Cost/month | ~$0–2 | ~$10–15 | ~$8 |
| Cold starts | Possible (keep_warm mitigates) | None (min 1 replica) | None |
| Deploy method | `func publish --remote-build` | `docker push` + CLI | SSH + git pull |
| Complexity | Low | Medium | High |
| Best for | Dev / demo | Production | Full control |

### Container Apps characteristics
- Runs any Docker container — no platform-specific SDK needed
- `minReplicas: 1` → one container always alive, responses in <1s
- Same env vars as Functions (just set in Azure Portal or CLI)
- Existing `src/app.py` (aiohttp) works as-is — just needs a Dockerfile (~10 lines)
- Auto-scales on HTTP traffic
- Real-time log streaming via `az containerapp logs tail`
- Built-in HTTPS with auto-managed TLS cert
- Cost: ~$0.000024/vCPU-second + ~$0.000003/GB-second → ~$10/month for 0.25 vCPU always-on

### Migration path (when ready)
1. Write `Dockerfile` (10 lines, base image `python:3.11-slim`)
2. `az acr create` + `docker build && docker push`
3. `az containerapp create` with env vars
4. Update Bot Service endpoint URL
5. Update `BOT_DOMAIN` env var

---

## Deployment

```bash
# From teams-agent/ directory in Git Bash:
export PATH="$PATH:/c/Program Files/Microsoft SDKs/Azure/CLI2/wbin"
func azure functionapp publish mayihear-agent --python --remote-build
```

Webhook subscription auto-renews every 50 minutes via timer trigger.
Re-register manually if needed: `python register_webhook.py`
