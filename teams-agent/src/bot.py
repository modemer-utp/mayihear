"""
Teams activity handler with conversational state machine:
  - Webhook fires → insights shown to user → confirm / regenerate / cancel
  - Board selection: user can choose which Monday board to publish to
  - Proactive messaging: bot initiates conversation when meeting is processed
  - State persisted in Azure Table Storage — survives redeploys + multi-instance scaling
  - Multi-user routing: conv refs stored per email, notifications go to the right person
  - Monday Q&A: user can ask natural-language questions about board data
"""
import os
import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from botbuilder.core import ActivityHandler, TurnContext, MessageFactory
from botbuilder.schema import ConversationReference

import pipeline
from tools.monday import list_boards, create_meeting_item
from tools.monday_qa import ask_monday
from tools.llm import generate_insights, format_insights_for_monday
from tools.graph import resolve_email_from_aad_id
from tools.state_store import (
    save_conversation_ref, load_conversation_ref,
    save_conv_ref_for_email, load_conv_ref_for_email,
)
from tools.table_state import get_conv_state, set_conv_state

_executor = ThreadPoolExecutor(max_workers=4)
logger = logging.getLogger(__name__)

# ── Global adapter reference (set from function_app.py after adapter is created) ──
_adapter = None

def set_adapter(adapter):
    global _adapter
    _adapter = adapter

# ── In-memory caches (lightweight, rebuilt from blob on cold start) ────────────
_conv_refs: dict = {}            # key → ConversationReference (any user, fast path)
_conv_refs_by_email: dict = {}   # email → ConversationReference (for routing)
_last_processed: dict = {}



class MayiHearBot(ActivityHandler):

    # ── Incoming messages ──────────────────────────────────────────────────────

    async def on_message_activity(self, turn_context: TurnContext):
        _save_ref(turn_context)

        conv_id = turn_context.activity.conversation.id
        raw = (turn_context.activity.text or "").strip()
        state = get_conv_state(conv_id)

        text_lower = raw.lower()

        if raw.startswith("/"):
            await self._handle_slash(turn_context, raw, state, conv_id)
        elif text_lower in ("hola", "hi", "hello", "ayuda", "help", "inicio", "start", ""):
            await self._cmd_welcome(turn_context, state)
        elif self._is_prompt_intent(text_lower):
            # Check estructura BEFORE queue — template content may contain "pendiente"
            if state.get("awaiting_prompt"):
                state = {**state, "awaiting_prompt": False}
                set_conv_state(conv_id, state)
            await self._cmd_prompt_dispatch(turn_context, raw, text_lower, state, conv_id)
        elif self._is_queue_intent(text_lower):
            await self._cmd_natural_queue(turn_context, raw, text_lower, state, conv_id)
        elif self._is_past_meetings_intent(text_lower):
            await self._cmd_past_meetings(turn_context)
        elif self._is_meeting_insights_intent(text_lower):
            await self._cmd_meeting_insights(turn_context, raw, text_lower, state, conv_id)
        elif state.get("awaiting_prompt"):
            # Only save as estructura if no other intent matched
            await self._save_custom_prompt(turn_context, raw, state, conv_id)
        else:
            await self._cmd_ask_monday(turn_context, raw, state)

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                state = get_conv_state(turn_context.activity.conversation.id)
                await self._cmd_welcome(turn_context, state)

    # ── Commands ───────────────────────────────────────────────────────────────

    async def _cmd_welcome(self, turn_context: TurnContext, state: dict):
        board_name = state.get("selected_board_name") if state.get("board_explicitly_selected") else "UTP - Roadmap proyectos - Producto"
        pending = state.get("pending")
        pending_note = (
            f"\n\n⏳ Tienes una reunión pendiente de confirmar: **{pending.get('subject', '')}**\n"
            "Usa `/confirmar`, `/regenerar` o `/cancelar`."
        ) if pending else ""
        saved_prompts = state.get("saved_prompts", {})
        acta_hint = (
            f"\n• `/acta usar <nombre>` — activar estructura guardada ({', '.join(saved_prompts.keys())})"
            if saved_prompts else ""
        )
        await turn_context.send_activity(
            MessageFactory.text(
                "Hola! Soy MayiHear 👋\n\n"
                "Proceso automáticamente las reuniones de Teams y publico insights en Monday.\n\n"
                f"📌 Tablero actual: **{board_name}**"
                f"{pending_note}\n\n"
                "**Comandos:**\n"
                "• `/boards` — ver tableros · `/select <n>` — cambiar tablero\n"
                "• `/confirmar` · `/regenerar` · `/cancelar` — gestionar reunión actual\n"
                "• `/cola` — ver reuniones en cola\n"
                "• `/acta` — ver/cambiar estructura de acta · `/acta lista` — estructuras guardadas\n"
                f"• `/status` · `/last` — estado e información{acta_hint}\n\n"
                "**Lenguaje natural:**\n"
                "• _¿qué reuniones tengo pendientes?_ · _elimina de la cola [reunión]_\n"
                "• _quiero ver reuniones anteriores_ · _resumir [nombre de reunión]_\n"
                "• _dame insights de [reunión]_ · _¿qué proyectos están en proceso?_\n"
                "• _acta_ · _estructura_ · _¿qué estructura de acta tengo?_"
            )
        )

    async def _cmd_ayuda(self, turn_context: TurnContext):
        await turn_context.send_activity(MessageFactory.text(
            "**Guía de uso — MayiHear** 📖\n\n"

            "**📋 Ver reuniones con transcripción:**\n"
            "• _reuniones_\n"
            "• _busca las últimas reuniones_\n"
            "• _reuniones con transcripción_\n"
            "• _quiero ver reuniones anteriores_\n\n"

            "**🔍 Obtener insights de una reunión:**\n"
            "• _resumir [nombre de reunión]_\n"
            "• _dame insights de [nombre de reunión]_\n"
            "• _puedes darme los insights de la reunion [nombre]_\n\n"

            "**✅ Gestionar reuniones pendientes:**\n"
            "• `/confirmar` · `/regenerar` · `/cancelar`\n"
            "• _¿qué reuniones tengo pendientes?_ · _cola_\n"
            "• _elimina de la cola [nombre de reunión]_\n"
            "• _regenera [nombre de reunión]_\n\n"

            "**📝 Estructura de acta:**\n"
            "• _acta_ — ver/cambiar estructura actual\n"
            "• _crea una nueva estructura de acta con lo siguiente: [tu plantilla]_\n"
            "• `/acta lista` — estructuras guardadas\n"
            "• `/acta guardar [nombre]` — guardar la actual\n"
            "• `/acta usar [nombre]` — activar una guardada\n"
            "• `/acta reset` — volver a la estructura por defecto\n\n"

            "**📊 Preguntar sobre Monday:**\n"
            "• _¿qué proyectos están en proceso?_\n"
            "• _¿cuáles son las tareas pendientes de [proyecto]?_\n"
            "• _¿quién es responsable de [iniciativa]?_\n\n"

            "**🔧 Otros comandos:**\n"
            "• `/boards` — ver tableros · `/select <n>` — cambiar tablero\n"
            "• `/status` · `/last` — estado e información\n"
            "• `/ayuda` — mostrar esta guía"
        ))

    async def _cmd_show_boards(self, turn_context: TurnContext, conv_id: str, state: dict):
        loop = asyncio.get_event_loop()
        try:
            boards = await loop.run_in_executor(_executor, list_boards)
        except Exception as e:
            await turn_context.send_activity(MessageFactory.text(f"Error al obtener tableros: {e}"))
            return

        if not boards:
            await turn_context.send_activity(MessageFactory.text("No encontré tableros en Monday."))
            return

        lines = ["**Tableros disponibles en Monday:**\n"]
        for i, b in enumerate(boards, 1):
            marker = " ✅" if b["id"] == (state.get("selected_board_id") or os.environ.get("MONDAY_BOARD_ID")) else ""
            lines.append(f"**{i}.** {b['name']}{marker}")
        lines.append("\nUsa `/select <número>` para cambiar de tablero.")

        set_conv_state(conv_id, {**state, "boards_cache": boards})
        await turn_context.send_activity(MessageFactory.text("\n".join(lines)))

    async def _cmd_last_meeting(self, turn_context: TurnContext):
        if _last_processed:
            await turn_context.send_activity(
                MessageFactory.text(
                    f"**Última reunión procesada:** {_last_processed['subject']}\n"
                    f"📌 Monday item: {_last_processed.get('item_id', 'pendiente')}\n\n"
                    f"{_last_processed['insights_text']}"
                )
            )
        else:
            await turn_context.send_activity(
                MessageFactory.text("Aún no he procesado ninguna reunión en esta sesión.")
            )

    async def _handle_slash(self, turn_context: TurnContext, text: str, state: dict, conv_id: str):
        parts = text.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/acta", "/estructura", "/prompt", "/formato"):
            await self._handle_prompt_slash(turn_context, arg, state, conv_id)
        elif cmd in ("/queue", "/cola"):
            await self._cmd_show_queue(turn_context, state)
        elif cmd == "/boards":
            await self._cmd_show_boards(turn_context, conv_id, state)
        elif cmd == "/select":
            await self._cmd_select_board(turn_context, arg, state, conv_id)
        elif cmd in ("/confirm", "/confirmar"):
            await self._slash_confirm(turn_context, state, conv_id)
        elif cmd in ("/cancel", "/cancelar"):
            await self._slash_cancel(turn_context, state, conv_id)
        elif cmd in ("/regenerate", "/regenerar"):
            await self._slash_regenerate(turn_context, state, conv_id)
        elif cmd == "/status":
            await turn_context.send_activity(
                MessageFactory.text("✅ MayiHear está activo. Procesando reuniones automáticamente cuando terminan.")
            )
        elif cmd in ("/last", "/ultima"):
            await self._cmd_last_meeting(turn_context)
        elif cmd in ("/help", "/ayuda"):
            await self._cmd_ayuda(turn_context)
        else:
            await turn_context.send_activity(
                MessageFactory.text(
                    f"Comando no reconocido: `{cmd}`\n\n"
                    "Comandos: `/boards` · `/select <n>` · `/confirmar` · `/cancelar` · `/regenerar` · `/cola` · `/status` · `/last`"
                )
            )

    async def _cmd_select_board(self, turn_context: TurnContext, arg: str, state: dict, conv_id: str):
        boards = state.get("boards_cache", [])
        if not boards:
            await turn_context.send_activity(MessageFactory.text("Primero usa `/boards` para ver la lista de tableros."))
            return
        try:
            idx = int(arg) - 1
            if 0 <= idx < len(boards):
                chosen = boards[idx]
                set_conv_state(conv_id, {
                    **state,
                    "selected_board_id": chosen["id"],
                    "selected_board_name": chosen["name"],
                    "board_explicitly_selected": True,
                })
                await turn_context.send_activity(
                    MessageFactory.text(f"✅ Tablero cambiado a: **{chosen['name']}**")
                )
                return
        except ValueError:
            pass
        await turn_context.send_activity(
            MessageFactory.text(f"Usa un número válido de la lista. Ejemplo: `/select 1`")
        )

    async def _slash_confirm(self, turn_context: TurnContext, state: dict, conv_id: str):
        pending = state.get("pending")
        if not pending:
            await turn_context.send_activity(MessageFactory.text("No hay ninguna reunión pendiente de confirmar."))
            return

        board_name = state.get("selected_board_name") if state.get("board_explicitly_selected") else "UTP - Roadmap proyectos - Producto"

        # First /confirm → show preview and ask for explicit approval
        if not state.get("pending_previewed"):
            set_conv_state(conv_id, {**state, "pending_previewed": True})
            await turn_context.send_activity(
                MessageFactory.text(
                    f"📋 **Vista previa — {pending.get('subject', 'Reunión')}**\n\n"
                    f"{pending['insights_text']}\n\n"
                    f"---\n"
                    f"Se publicará en **{board_name}**.\n"
                    f"¿Confirmas? → `/confirmar` para publicar · `/regenerar` para regenerar · `/cancelar` para descartar"
                )
            )
            return

        # Second /confirm → publish
        board_id = state.get("selected_board_id") if state.get("board_explicitly_selected") else os.environ.get("MONDAY_BOARD_ID")
        await turn_context.send_activity(MessageFactory.text("⏳ Publicando en Monday..."))
        loop = asyncio.get_event_loop()
        try:
            item_id = await loop.run_in_executor(
                _executor, pipeline.post_to_monday,
                pending["subject"], pending["insights_text"], board_id
            )
        except Exception as e:
            await turn_context.send_activity(MessageFactory.text(f"❌ Error publicando: {e}"))
            return
        _last_processed.update({**pending, "item_id": item_id})

        # Advance queue — show next preview if any
        queue = list(state.get("pending_queue", []))
        if queue:
            next_pending = queue.pop(0)
            set_conv_state(conv_id, {**state, "pending": next_pending, "pending_queue": queue, "pending_previewed": False})
        else:
            set_conv_state(conv_id, {**state, "pending": None, "pending_queue": [], "pending_previewed": False})

        await turn_context.send_activity(
            MessageFactory.text(f"✅ **{pending['subject']}** publicada en **{board_name}** → item `{item_id}`")
        )
        if queue:
            next_pending_item = queue[0] if queue else state.get("pending_queue", [{}])[0] if state.get("pending_queue") else None
            # next_pending was already popped above
            await turn_context.send_activity(
                MessageFactory.text(
                    f"📝 **Siguiente reunión pendiente: {next_pending.get('subject', 'Reunión')}**\n\n"
                    f"{next_pending['insights_text']}\n\n"
                    "Usa `/confirmar` para revisar y publicar · `/regenerar` · `/cancelar`"
                )
            )

    async def _slash_cancel(self, turn_context: TurnContext, state: dict, conv_id: str):
        pending = state.get("pending")
        if not pending:
            await turn_context.send_activity(MessageFactory.text("No hay ninguna reunión pendiente."))
            return
        queue = list(state.get("pending_queue", []))
        if queue:
            next_pending = queue.pop(0)
            set_conv_state(conv_id, {**state, "pending": next_pending, "pending_queue": queue, "pending_previewed": False})
            await turn_context.send_activity(
                MessageFactory.text(
                    f"❌ Cancelado. Los insights de **{pending.get('subject', 'la reunión')}** no se publicaron.\n\n"
                    f"📝 **Siguiente reunión pendiente: {next_pending.get('subject', 'Reunión')}**\n\n"
                    f"{next_pending['insights_text']}\n\n"
                    "Usa `/confirmar` para revisar y publicar · `/regenerar` · `/cancelar`"
                )
            )
        else:
            set_conv_state(conv_id, {**state, "pending": None, "pending_queue": [], "pending_previewed": False})
            await turn_context.send_activity(
                MessageFactory.text(f"❌ Cancelado. Los insights de **{pending.get('subject', 'la reunión')}** no se publicaron.")
            )

    async def _slash_regenerate(self, turn_context: TurnContext, state: dict, conv_id: str):
        # Use last processed meeting (auto-post flow — no pending state)
        source = _last_processed if _last_processed else None
        if not source or not source.get("transcript_text"):
            await turn_context.send_activity(MessageFactory.text(
                "No hay ninguna reunión reciente para regenerar. Procesa una reunión primero."
            ))
            return
        custom_prompt = state.get("custom_prompt")
        subject = source.get("subject", "Reunión")
        board_id = state.get("selected_board_id") if state.get("board_explicitly_selected") else os.environ.get("MONDAY_BOARD_ID")
        board_name = state.get("selected_board_name") if state.get("board_explicitly_selected") else "UTP - Roadmap proyectos - Producto"

        await turn_context.send_activity(MessageFactory.text(
            "🔄 Regenerando" + (" con tu estructura de acta..." if custom_prompt else "...")
        ))
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                _executor, pipeline.generate,
                source["transcript_text"], subject, custom_prompt
            )
            item_id = await loop.run_in_executor(
                _executor, pipeline.post_to_monday,
                subject, result["insights_text"], board_id
            )
            _last_processed.update({**result, "item_id": item_id})
        except Exception as e:
            await turn_context.send_activity(MessageFactory.text(f"❌ Error: {e}"))
            return
        await turn_context.send_activity(MessageFactory.text(
            f"✅ **{subject}** regenerada y publicada en **{board_name}**\n\n{result['insights_text']}"
        ))

    # ── Custom prompt management ───────────────────────────────────────────────

    def _is_prompt_intent(self, text: str) -> bool:
        # Single-word triggers
        words = text.split()
        if any(w in ("acta", "estructura") for w in words):
            return True
        return any(w in text for w in [
            "quiero que extraigas", "quiero que te concentres", "quiero que generes",
            "estructura de acta", "cambiar la estructura", "cambia la estructura",
            "nueva estructura", "mi estructura", "mis estructuras",
            "acta de reunión", "acta de reunion", "formato de acta",
            "personalizar", "personaliza", "cómo extraes", "como extraes",
            "que estructura", "qué estructura", "ver estructuras", "ver actas",
            "guarda esta estructura", "guarda el acta", "guardar como", "guárdalo como",
            "usa la estructura", "usar la estructura", "usa el acta", "usar el acta",
            "lista de estructuras", "borra la estructura", "borrar la estructura",
            "muéstrame mis estructuras", "muestrame mis estructuras",
            "que actas hay", "qué actas hay", "mis actas", "mis estructuras guardadas",
            "con lo siguiente", "nueva estructura de acta", "crea una nueva", "crea un nueva",
        ])

    def _is_meeting_insights_intent(self, text: str) -> bool:
        return any(w in text for w in [
            "resumir", "resumen de", "insights de", "dame insights",
            "qué se habló", "que se habló", "qué pasó en", "que paso en",
            "dame el resumen", "dime qué se habló", "dime que se hablo",
            "extrae los insights", "genera el acta de",
        ])

    # ── Named-prompt slash handler ─────────────────────────────────────────────

    async def _handle_prompt_slash(self, turn_context: TurnContext, arg: str, state: dict, conv_id: str):
        """Handle /acta [subcommand] — supports named structures."""
        arg_stripped = arg.strip()
        arg_lower = arg_stripped.lower()
        saved: dict = state.get("saved_prompts", {})
        custom = state.get("custom_prompt")
        active_name = state.get("active_prompt_name")

        if arg_lower == "lista":
            await self._cmd_list_prompts(turn_context, state)
        elif arg_lower == "reset":
            set_conv_state(conv_id, {**state, "custom_prompt": None, "active_prompt_name": None, "awaiting_prompt": False})
            await turn_context.send_activity(MessageFactory.text(
                "✅ Vuelves a la estructura por defecto (resumen, decisiones, tareas, preguntas abiertas)."
            ))
        elif arg_lower.startswith("guardar "):
            name = arg_stripped[8:].strip()
            if not name:
                await turn_context.send_activity(MessageFactory.text("Escribe un nombre: `/acta guardar acta formal`"))
                return
            if not custom:
                await turn_context.send_activity(MessageFactory.text(
                    "No tienes una estructura activa para guardar. Escribe una primero con `/acta`."
                ))
                return
            saved[name] = custom
            set_conv_state(conv_id, {**state, "saved_prompts": saved, "active_prompt_name": name})
            await turn_context.send_activity(MessageFactory.text(
                f"✅ Estructura guardada como **{name}**.\n"
                f"Actívala más adelante con `/acta usar {name}`."
            ))
        elif arg_lower.startswith("usar "):
            name = arg_stripped[5:].strip()
            match = next((k for k in saved if k.lower() == name.lower()), None)
            if not match:
                match = next((k for k in saved if name.lower() in k.lower()), None)
            if not match:
                await turn_context.send_activity(MessageFactory.text(
                    f"No encontré una estructura llamada **{name}**.\n"
                    f"Usa `/acta lista` para ver tus estructuras guardadas."
                ))
                return
            set_conv_state(conv_id, {**state, "custom_prompt": saved[match], "active_prompt_name": match, "awaiting_prompt": False})
            await turn_context.send_activity(MessageFactory.text(
                f"✅ Usando la estructura **{match}**:\n\n_{saved[match]}_"
            ))
        elif arg_lower.startswith("borrar "):
            name = arg_stripped[7:].strip()
            match = next((k for k in saved if k.lower() == name.lower()), None)
            if not match:
                await turn_context.send_activity(MessageFactory.text(
                    f"No encontré una estructura llamada **{name}**. Usa `/acta lista`."
                ))
                return
            del saved[match]
            new_active = active_name if active_name != match else None
            new_custom = custom if active_name != match else None
            set_conv_state(conv_id, {**state, "saved_prompts": saved, "active_prompt_name": new_active, "custom_prompt": new_custom})
            await turn_context.send_activity(MessageFactory.text(f"🗑️ Estructura **{match}** eliminada."))
        elif arg_stripped in saved or any(arg_stripped.lower() == k.lower() for k in saved):
            # Direct /acta <nombre> → activate it
            match = next((k for k in saved if k.lower() == arg_stripped.lower()), arg_stripped)
            set_conv_state(conv_id, {**state, "custom_prompt": saved[match], "active_prompt_name": match, "awaiting_prompt": False})
            await turn_context.send_activity(MessageFactory.text(
                f"✅ Usando la estructura **{match}**:\n\n_{saved[match]}_"
            ))
        else:
            await self._cmd_show_prompt(turn_context, state, conv_id)

    async def _cmd_list_prompts(self, turn_context: TurnContext, state: dict):
        saved: dict = state.get("saved_prompts", {})
        active_name = state.get("active_prompt_name")
        if not saved:
            await turn_context.send_activity(MessageFactory.text(
                "No tienes estructuras guardadas todavía.\n\n"
                "Escribe `/acta` para crear una, luego `/acta guardar <nombre>` para guardarla."
            ))
            return
        lines = ["**Tus estructuras de acta guardadas:**\n"]
        for name, text in saved.items():
            marker = " ✅ (activa)" if name == active_name else ""
            preview = text[:80] + "..." if len(text) > 80 else text
            lines.append(f"• **{name}**{marker} — _{preview}_")
        lines.append("\nUsa `/acta usar <nombre>` para activar una · `/acta borrar <nombre>` para eliminar.")
        await turn_context.send_activity(MessageFactory.text("\n".join(lines)))

    async def _cmd_show_prompt(self, turn_context: TurnContext, state: dict, conv_id: str):
        custom = state.get("custom_prompt")
        active_name = state.get("active_prompt_name")
        saved: dict = state.get("saved_prompts", {})

        if custom:
            name_str = f" (**{active_name}**)" if active_name else ""
            saved_section = ""
            if saved:
                saved_names = " · ".join(f"**{k}**" for k in saved)
                saved_section = f"\n\n📂 Estructuras guardadas: {saved_names}\nUsa `/acta usar <nombre>` para cambiar."
            await turn_context.send_activity(MessageFactory.text(
                f"📝 **Estructura de acta actual{name_str}:**\n\n_{custom}_\n\n"
                "Escribe tus nuevas instrucciones en el siguiente mensaje para cambiarla.\n"
                f"O usa `/acta reset` para volver a la estructura por defecto.{saved_section}"
            ))
        else:
            saved_section = ""
            if saved:
                saved_names = " · ".join(f"**{k}**" for k in saved)
                saved_section = f"\n\n📂 Estructuras guardadas: {saved_names}\nUsa `/acta usar <nombre>` para activar una."
            await turn_context.send_activity(MessageFactory.text(
                "Actualmente usas la **estructura por defecto** (resumen, decisiones, tareas, preguntas abiertas).\n\n"
                "Escribe tus instrucciones en el siguiente mensaje para personalizar la estructura de acta.\n\n"
                "**Ejemplos:**\n"
                "• _Genera un acta formal con: fecha, participantes, objetivos, puntos tratados, acuerdos con responsable y fecha límite, y próximos pasos._\n"
                "• _Extrae solo las tareas y compromisos: nombre del responsable, descripción y fecha de entrega._\n"
                "• _Resumen ejecutivo en máximo 5 bullets enfocado en decisiones de negocio e impacto en el roadmap._\n"
                "• _Estructura de seguimiento: estado de avance por iniciativa, riesgos identificados y decisiones de priorización._\n"
                f"• _Solo quiero saber qué se decidió y quién es responsable de qué. Sin contexto adicional._{saved_section}"
            ))
        set_conv_state(conv_id, {**state, "awaiting_prompt": True})

    async def _cmd_prompt_dispatch(self, turn_context: TurnContext, raw: str, text_lower: str, state: dict, conv_id: str):
        """Natural-language acta structure management."""
        saved: dict = state.get("saved_prompts", {})
        custom = state.get("custom_prompt")

        # Inline creation: "crea una nueva estructura de acta con lo siguiente: ..."
        inline_kw = ["con lo siguiente", "con la siguiente estructura", "con este formato"]
        for kw in inline_kw:
            if kw in text_lower:
                idx = text_lower.find(kw) + len(kw)
                content = raw[idx:].lstrip(": \n").strip()
                if content:
                    set_conv_state(conv_id, {**state, "custom_prompt": content, "active_prompt_name": None, "awaiting_prompt": False})
                    save_hint = "\n\nUsa `/acta guardar <nombre>` para guardarla con un nombre y reutilizarla."
                    await turn_context.send_activity(MessageFactory.text(
                        f"✅ Estructura de acta guardada. La usaré en las próximas reuniones y al `/regenerar`.{save_hint}"
                    ))
                    return
                # Keyword found but no content after it → enter edit mode
                await self._cmd_show_prompt(turn_context, state, conv_id)
                return

        save_kw = ["guarda esta estructura", "guarda el acta", "guardar como", "guárdalo como", "guárdala como"]
        use_kw = ["usa la estructura", "usar la estructura", "usa el acta", "usar el acta", "activa la estructura"]
        list_kw = ["mis estructuras", "ver estructuras", "que actas hay", "qué actas hay",
                   "mis actas", "lista de estructuras", "muestrame mis estructuras", "muéstrame mis estructuras"]
        delete_kw = ["borra la estructura", "borrar la estructura", "elimina la estructura", "eliminar estructura"]

        if any(w in text_lower for w in save_kw):
            idx = text_lower.find(" como ")
            name = raw[idx + 6:].strip() if idx != -1 else ""
            if not name or not custom:
                await turn_context.send_activity(MessageFactory.text(
                    "Escribe `/acta guardar <nombre>` para guardar la estructura activa."
                ))
                return
            saved[name] = custom
            set_conv_state(conv_id, {**state, "saved_prompts": saved, "active_prompt_name": name})
            await turn_context.send_activity(MessageFactory.text(
                f"✅ Estructura guardada como **{name}**.\n"
                f"Actívala más adelante con `/acta usar {name}`."
            ))
        elif any(w in text_lower for w in use_kw):
            idx = text_lower.find(" de ")
            name = raw[idx + 4:].strip() if idx != -1 else ""
            match = next((k for k in saved if name.lower() in k.lower() or k.lower() in name.lower()), None)
            if not match:
                await self._cmd_list_prompts(turn_context, state)
                return
            set_conv_state(conv_id, {**state, "custom_prompt": saved[match], "active_prompt_name": match, "awaiting_prompt": False})
            await turn_context.send_activity(MessageFactory.text(f"✅ Usando la estructura **{match}**."))
        elif any(w in text_lower for w in list_kw):
            await self._cmd_list_prompts(turn_context, state)
        elif any(w in text_lower for w in delete_kw):
            await turn_context.send_activity(MessageFactory.text(
                "Usa `/prompt borrar <nombre>` para eliminar un formato guardado."
            ))
        else:
            # Wants to create/change prompt
            await self._cmd_show_prompt(turn_context, state, conv_id)

    async def _save_custom_prompt(self, turn_context: TurnContext, raw: str, state: dict, conv_id: str):
        if raw.lower() in ("reset", "default", "por defecto", "predeterminado"):
            set_conv_state(conv_id, {**state, "custom_prompt": None, "active_prompt_name": None, "awaiting_prompt": False})
            await turn_context.send_activity(MessageFactory.text(
                "✅ Vuelves a la estructura por defecto (resumen, decisiones, tareas, preguntas abiertas)."
            ))
        else:
            set_conv_state(conv_id, {**state, "custom_prompt": raw, "active_prompt_name": None, "awaiting_prompt": False})
            saved: dict = state.get("saved_prompts", {})
            if saved:
                save_hint = "\n\nUsa `/acta guardar <nombre>` si quieres reutilizarla luego."
            else:
                save_hint = "\n\nConsejo: usa `/acta guardar <nombre>` para guardarla y reutilizarla en futuras reuniones."
            await turn_context.send_activity(MessageFactory.text(
                f"✅ Estructura de acta guardada. La usaré en las próximas reuniones y al `/regenerar`.\n\n"
                f"**Tu estructura:**\n_{raw}_{save_hint}"
            ))

    # ── Natural language intent helpers ───────────────────────────────────────

    def _is_queue_intent(self, text: str) -> bool:
        queue_words = ["cola", "pendiente", "pendientes", "en espera", "queue"]
        action_words = ["elimina", "quita", "borra", "saca", "eliminar", "quitar",
                        "borrar", "sacar", "regenera", "regenerar", "ver cola",
                        "mostrar cola", "qué hay", "que hay", "ver la cola"]
        return any(w in text for w in queue_words) or any(w in text for w in action_words)

    def _is_past_meetings_intent(self, text: str) -> bool:
        words = text.split()
        # "reuniones" alone (plural) → listing intent
        if "reuniones" in words:
            return True
        return any(w in text for w in [
            "anteriores", "pasadas", "historial", "reuniones pasadas",
            "reuniones anteriores", "ver reuniones", "reuniones procesadas",
            "que reuniones", "qué reuniones", "mis reuniones",
            "ultimas reuniones", "últimas reuniones", "reuniones recientes",
            "reuniones transcritas", "con transcripcion", "con transcripción",
            "busca reuniones", "buscar reuniones", "listar reuniones",
        ])

    async def _cmd_show_queue(self, turn_context: TurnContext, state: dict):
        pending = state.get("pending")
        queue = state.get("pending_queue", [])
        if not pending and not queue:
            await turn_context.send_activity(MessageFactory.text("No hay reuniones pendientes en este momento."))
            return
        lines = ["**Cola de reuniones:**\n"]
        if pending:
            lines.append(f"📋 Revisando ahora: **{pending.get('subject', 'Reunión')}**")
        for i, item in enumerate(queue, 1):
            lines.append(f"  {i}. **{item.get('subject', 'Reunión')}**")
        if not queue:
            lines.append("\n_Sin más reuniones en cola._")
        lines.append("\nUsa `/confirmar` · `/cancelar` · `/regenerar`")
        await turn_context.send_activity(MessageFactory.text("\n".join(lines)))

    async def _cmd_natural_queue(self, turn_context: TurnContext, raw: str, text_lower: str, state: dict, conv_id: str):
        """Handle natural language queue management."""
        pending = state.get("pending")
        queue = list(state.get("pending_queue", []))

        remove_words = ["elimina", "quita", "borra", "saca", "eliminar", "quitar", "borrar", "sacar"]
        regen_words  = ["regenera", "regenerar", "vuelve a generar", "genera de nuevo"]

        is_remove = any(w in text_lower for w in remove_words)
        is_regen  = any(w in text_lower for w in regen_words)

        if not is_remove and not is_regen:
            # Just wants to see the queue
            await self._cmd_show_queue(turn_context, state)
            return

        # Find which meeting the user is referring to
        all_items = ([pending] if pending else []) + queue
        target = None
        target_is_pending = False

        for i, item in enumerate(all_items):
            subj = item.get("subject", "").lower()
            if subj and (subj in text_lower or any(word in subj for word in text_lower.split() if len(word) > 3)):
                target = item
                target_is_pending = (i == 0 and pending is not None)
                break

        # If no name match, default to current pending
        if target is None and pending:
            target = pending
            target_is_pending = True

        if target is None:
            await self._cmd_show_queue(turn_context, state)
            await turn_context.send_activity(MessageFactory.text("¿A cuál reunión te refieres? Menciona el nombre."))
            return

        subj_name = target.get("subject", "la reunión")

        if is_regen:
            # Regenerate: bring to front if in queue, then regenerate
            if not target_is_pending:
                queue.remove(target)
                if pending:
                    queue.insert(0, pending)
                set_conv_state(conv_id, {**state, "pending": target, "pending_queue": queue, "pending_previewed": False})
                state = get_conv_state(conv_id)
            await self._slash_regenerate(turn_context, state, conv_id)

        elif is_remove:
            if target_is_pending:
                if queue:
                    next_item = queue.pop(0)
                    set_conv_state(conv_id, {**state, "pending": next_item, "pending_queue": queue, "pending_previewed": False})
                    await turn_context.send_activity(MessageFactory.text(
                        f"✅ **{subj_name}** eliminada.\n\n"
                        f"Ahora revisando: **{next_item.get('subject', 'Reunión')}**\n\n"
                        f"{next_item['insights_text']}\n\n"
                        "Usa `/confirmar` · `/regenerar` · `/cancelar`"
                    ))
                else:
                    set_conv_state(conv_id, {**state, "pending": None, "pending_queue": [], "pending_previewed": False})
                    await turn_context.send_activity(MessageFactory.text(f"✅ **{subj_name}** eliminada. No hay más reuniones pendientes."))
            else:
                queue.remove(target)
                set_conv_state(conv_id, {**state, "pending_queue": queue})
                await turn_context.send_activity(MessageFactory.text(f"✅ **{subj_name}** eliminada de la cola."))

    async def _cmd_past_meetings(self, turn_context: TurnContext):
        await turn_context.send_activity(MessageFactory.text("🔍 Buscando reuniones anteriores..."))
        loop = asyncio.get_event_loop()
        try:
            meetings = await loop.run_in_executor(_executor, self._fetch_past_meetings)
            if not meetings:
                await turn_context.send_activity(MessageFactory.text("No encontré reuniones anteriores con transcripción."))
                return
            lines = ["**Reuniones anteriores con transcripción:**\n"]
            for m in meetings:
                lines.append(f"• {m['date']} — **{m['subject']}**")
            await turn_context.send_activity(MessageFactory.text("\n".join(lines)))
        except Exception as e:
            await turn_context.send_activity(MessageFactory.text(f"Error al obtener reuniones: {e}"))

    def _fetch_past_meetings(self) -> list:
        import requests as _req
        from tools.graph_client import get_token, get_user_id
        GRAPH = "https://graph.microsoft.com/v1.0"
        token = get_token()
        organizer = os.environ.get("ORGANIZER_TEAMS_MAIL", "")
        uid = get_user_id(token, organizer)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GRAPH}/users/{uid}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{uid}')"
        transcripts = sorted(
            _req.get(url, headers=headers).json().get("value", []),
            key=lambda t: t.get("createdDateTime", ""), reverse=True
        )[:10]
        results = []
        for t in transcripts:
            mid = t.get("meetingId", "")
            date = t.get("createdDateTime", "")[:10]
            try:
                subj = _req.get(f"{GRAPH}/users/{uid}/onlineMeetings/{mid}?$select=subject", headers=headers).json().get("subject") or "Reunión Teams"
            except Exception:
                subj = "Reunión Teams"
            results.append({"date": date, "subject": subj})
        return results

    # ── Meeting insights by name ───────────────────────────────────────────────

    async def _cmd_meeting_insights(self, turn_context: TurnContext, raw: str, text_lower: str, state: dict, conv_id: str):
        """Find a past/queued meeting by name and show or generate its insights."""
        # Keywords to strip when extracting the meeting name from the query
        skip = {
            "de", "la", "el", "los", "las", "en", "un", "una", "que", "qué", "me",
            "puedes", "puedo", "podrías", "podrias", "dame", "darme", "insights",
            "resumir", "resumen", "acta", "sobre", "reunión", "reunion",
            "habló", "hablo", "pasó", "paso", "se", "genera", "extrae", "dime",
            "del", "al", "por", "para", "como", "cómo", "cuál", "cual",
            "anterior", "pasada", "última", "ultima",
        }
        # Normalize: strip accents for comparison
        import unicodedata
        def _norm(w):
            return unicodedata.normalize("NFD", w).encode("ascii", "ignore").decode()
        skip_norm = {_norm(w) for w in skip}
        query_words = [w for w in text_lower.split() if len(w) > 3 and _norm(w) not in skip_norm]

        if not query_words:
            # No specific name — show list so user can pick one
            await turn_context.send_activity(MessageFactory.text("¿Sobre cuál reunión? Aquí están las disponibles:"))
            await self._cmd_past_meetings(turn_context)
            return

        # 1. Check pending / queue first (no API call needed)
        all_queued = []
        if state.get("pending"):
            all_queued.append(state["pending"])
        all_queued.extend(state.get("pending_queue", []))

        query_words_norm = [_norm(w) for w in query_words]

        for item in all_queued:
            subj_norm = _norm(item.get("subject", "").lower())
            if any(w in subj_norm for w in query_words_norm):
                await turn_context.send_activity(MessageFactory.text(
                    f"📝 **{item.get('subject', 'Reunión')}** _(pendiente de confirmar)_\n\n"
                    f"{item['insights_text']}\n\n"
                    "Usa `/confirmar` para publicarla en Monday."
                ))
                return

        # 2. Search past meetings via Graph
        await turn_context.send_activity(MessageFactory.text("🔍 Buscando en reuniones anteriores..."))
        loop = asyncio.get_event_loop()
        try:
            past = await loop.run_in_executor(_executor, self._fetch_past_meetings_with_ids)
        except Exception as e:
            logger.exception("Failed to fetch past meetings for insights lookup")
            await self._cmd_ask_monday(turn_context, raw, state)
            return

        matched = None
        for m in past:
            subj_norm = _norm(m.get("subject", "").lower())
            if any(w in subj_norm for w in query_words_norm):
                matched = m
                break

        if not matched:
            # Nothing found — fall through to Monday Q&A
            await self._cmd_ask_monday(turn_context, raw, state)
            return

        await turn_context.send_activity(MessageFactory.text(
            f"📋 Encontré: **{matched['subject']}** ({matched['date']})\n⏳ Generando insights..."
        ))
        custom_prompt = state.get("custom_prompt")
        try:
            transcript_data = await loop.run_in_executor(
                _executor, pipeline.fetch_transcript,
                os.environ.get("ORGANIZER_TEAMS_MAIL", ""),
                matched["meeting_id"], matched["transcript_id"], matched["subject"]
            )
            result = await loop.run_in_executor(
                _executor, pipeline.generate,
                transcript_data["transcript_text"], matched["subject"], custom_prompt
            )
            await turn_context.send_activity(MessageFactory.text(
                f"📝 **{matched['subject']}** — {matched['date']}\n\n{result['insights_text']}"
            ))
        except Exception as e:
            await turn_context.send_activity(MessageFactory.text(f"❌ Error generando insights: {e}"))

    def _fetch_past_meetings_with_ids(self) -> list:
        """Like _fetch_past_meetings but includes meeting_id and transcript_id for transcript fetching."""
        import requests as _req
        from tools.graph_client import get_token, get_user_id
        GRAPH = "https://graph.microsoft.com/v1.0"
        token = get_token()
        organizer = os.environ.get("ORGANIZER_TEAMS_MAIL", "")
        uid = get_user_id(token, organizer)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GRAPH}/users/{uid}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{uid}')"
        resp = _req.get(url, headers=headers)
        transcripts = sorted(
            resp.json().get("value", []),
            key=lambda t: t.get("createdDateTime", ""), reverse=True
        )[:20]
        results = []
        for t in transcripts:
            mid = t.get("meetingId", "")
            tid = t.get("id", "")
            date = t.get("createdDateTime", "")[:10]
            try:
                subj = _req.get(
                    f"{GRAPH}/users/{uid}/onlineMeetings/{mid}?$select=subject",
                    headers=headers
                ).json().get("subject") or "Reunión Teams"
            except Exception:
                subj = "Reunión Teams"
            results.append({"date": date, "subject": subj, "meeting_id": mid, "transcript_id": tid})
        return results

    async def _cmd_ask_monday(self, turn_context: TurnContext, question: str, state: dict):
        """Answer a natural-language question about Monday board data using Gemini."""
        board_id = state.get("selected_board_id") if state.get("board_explicitly_selected") else os.environ.get("MONDAY_BOARD_ID")
        board_name = state.get("selected_board_name") if state.get("board_explicitly_selected") else "UTP - Roadmap proyectos - Producto"

        if not board_id:
            await turn_context.send_activity(
                MessageFactory.text("Primero selecciona un tablero con el comando **boards**.")
            )
            return

        await turn_context.send_activity(MessageFactory.text("🔍 Consultando Monday..."))
        loop = asyncio.get_event_loop()
        try:
            answer = await loop.run_in_executor(
                _executor, ask_monday, question, board_id, board_name
            )
            await turn_context.send_activity(MessageFactory.text(answer))
        except Exception as e:
            logger.exception("Monday Q&A failed")
            await turn_context.send_activity(MessageFactory.text(f"❌ Error consultando Monday: {e}"))


    # ── Webhook / Service Bus handler ──────────────────────────────────────────

    async def process_meeting_webhook(self, payload: dict) -> str:
        """
        Called by Service Bus trigger for each new transcript.
        Fetches transcript → generates insights → posts to Monday automatically.
        No confirmation step. Routes proactive message to the correct organizer.
        """
        resource_data = payload.get("resourceData", {})
        meeting_id = resource_data.get("meetingId") or payload.get("meetingId")
        transcript_id = resource_data.get("id") or payload.get("transcriptId")
        organizer_email = (
            resource_data.get("organizerEmail")
            or payload.get("organizerEmail")
            or os.environ.get("ORGANIZER_TEAMS_MAIL")
        )
        subject = resource_data.get("subject") or payload.get("subject") or "Reunión Teams"

        if not all([meeting_id, transcript_id, organizer_email]):
            logger.warning(f"Incomplete webhook payload: {payload}")
            return "Payload incompleto — se requiere meetingId, transcriptId y organizerEmail"

        loop = asyncio.get_event_loop()

        # Step 1+2: fetch transcript
        transcript_data = await loop.run_in_executor(
            _executor, pipeline.fetch_transcript,
            organizer_email, meeting_id, transcript_id, subject
        )

        # Skip if transcript has no meaningful content (empty / no speech)
        if not transcript_data.get("transcript_text", "").strip():
            logger.info(f"Empty transcript for '{subject}' — skipping")
            return f"Skipped '{subject}' — empty transcript"

        ref = _get_ref_for_organizer(organizer_email) or _get_any_ref()

        if ref and _adapter:
            async def _callback(ctx: TurnContext):
                conv_id = ctx.activity.conversation.id
                state = get_conv_state(conv_id)
                custom_prompt = state.get("custom_prompt")
                board_id = state.get("selected_board_id") if state.get("board_explicitly_selected") else os.environ.get("MONDAY_BOARD_ID")
                board_name = state.get("selected_board_name") if state.get("board_explicitly_selected") else "UTP - Roadmap proyectos - Producto"

                await ctx.send_activity(MessageFactory.text(f"⏳ Procesando **{subject}**..."))

                try:
                    # Generate insights
                    result = await loop.run_in_executor(
                        _executor, pipeline.generate,
                        transcript_data["transcript_text"], subject, custom_prompt
                    )

                    # Auto-post to Monday
                    item_id = await loop.run_in_executor(
                        _executor, pipeline.post_to_monday,
                        subject, result["insights_text"], board_id
                    )
                    _last_processed.update({**result, "item_id": item_id})

                    await ctx.send_activity(MessageFactory.text(
                        f"✅ **{subject}** publicada en **Actualizaciones** de **{board_name}**\n\n"
                        f"{result['insights_text']}\n\n"
                        f"Usa `/regenerar` si quieres cambiar la estructura y volver a publicar."
                    ))
                except Exception as e:
                    logger.exception(f"Pipeline failed for '{subject}': {e}")
                    await ctx.send_activity(MessageFactory.text(
                        f"❌ Error procesando **{subject}**: {str(e)[:200]}\n\n"
                        f"Usa `/regenerar` para reintentar cuando la reunión haya terminado."
                    ))

            await _adapter.continue_conversation(ref, _callback, os.environ.get("BOT_ID", ""))
            logger.info(f"Auto-posted '{subject}' for '{organizer_email}'")
            return f"Auto-posted '{subject}'"

        else:
            # No stored ref → post silently
            logger.warning(f"No conversation reference for '{organizer_email}' — posting silently")
            result = await loop.run_in_executor(
                _executor, pipeline.generate,
                transcript_data["transcript_text"], subject, None
            )
            item_id = await loop.run_in_executor(
                _executor, pipeline.post_to_monday,
                subject, result["insights_text"], None
            )
            _last_processed.update({**result, "item_id": item_id})
            return f"✅ Published '{subject}' → Monday item {item_id}"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _save_ref(turn_context: TurnContext):
    activity = turn_context.activity
    ref = TurnContext.get_conversation_reference(activity)
    key = (
        (activity.from_property.aad_object_id or "").strip()
        or activity.from_property.id
        or activity.conversation.id
    )
    _conv_refs[key] = ref

    # Serialize for blob storage
    ref_dict = {
        "activity_id": ref.activity_id,
        "bot": {"id": ref.bot.id, "name": ref.bot.name} if ref.bot else None,
        "channel_id": ref.channel_id,
        "conversation": ref.conversation.serialize() if ref.conversation else None,
        "locale": ref.locale,
        "service_url": ref.service_url,
        "user": {
            "id": ref.user.id,
            "name": ref.user.name,
            "aad_object_id": ref.user.aad_object_id,
        } if ref.user else None,
    }

    # Persist generic ref (fast path / fallback)
    try:
        save_conversation_ref(ref_dict)
    except Exception as e:
        logger.warning(f"Could not persist conversation ref: {e}")

    # Resolve email and persist email-keyed ref in background (non-blocking)
    aad_id = (activity.from_property.aad_object_id or "").strip()
    if aad_id:
        threading.Thread(
            target=_resolve_and_save_email_ref,
            args=(aad_id, ref_dict),
            daemon=True,
        ).start()


def _resolve_and_save_email_ref(aad_object_id: str, ref_dict: dict):
    """Resolve AAD object ID → email, then save ref keyed by email. Runs in background thread."""
    email = resolve_email_from_aad_id(aad_object_id)
    if email:
        _conv_refs_by_email[email] = _deserialize_ref(ref_dict)
        save_conv_ref_for_email(email, ref_dict)
        logger.info(f"Saved conv ref for email: {email}")


def _get_ref_for_organizer(organizer_email: str) -> ConversationReference | None:
    """
    Get conversation reference for a specific organizer email.
    Checks in-memory cache first, then blob storage.
    Returns None if not found (user has never chatted with the bot).
    """
    if not organizer_email:
        return None
    email = organizer_email.lower()

    # In-memory cache (fast path)
    ref = _conv_refs_by_email.get(email)
    if ref:
        return ref

    # Load from blob
    ref_dict = load_conv_ref_for_email(email)
    if ref_dict:
        ref = _deserialize_ref(ref_dict)
        if ref:
            _conv_refs_by_email[email] = ref
            return ref

    return None


def _get_any_ref() -> ConversationReference | None:
    """Fallback: return any stored conversation reference."""
    ref = next(iter(_conv_refs.values()), None)
    if ref:
        return ref

    ref_dict = load_conversation_ref()
    if not ref_dict:
        return None

    try:
        ref = _deserialize_ref(ref_dict)
        if ref:
            _conv_refs["__loaded__"] = ref
            logger.info("Conversation reference restored from blob storage")
        return ref
    except Exception as e:
        logger.warning(f"Could not restore conversation ref from blob: {e}")
        return None


def _deserialize_ref(ref_dict: dict) -> ConversationReference | None:
    """Deserialize a stored ref_dict → ConversationReference object."""
    try:
        from botbuilder.schema import ConversationAccount, ChannelAccount
        ref = ConversationReference()
        ref.activity_id = ref_dict.get("activity_id")
        ref.channel_id = ref_dict.get("channel_id")
        ref.locale = ref_dict.get("locale")
        ref.service_url = ref_dict.get("service_url")
        if ref_dict.get("bot"):
            ref.bot = ChannelAccount(id=ref_dict["bot"]["id"], name=ref_dict["bot"]["name"])
        if ref_dict.get("conversation"):
            ref.conversation = ConversationAccount.deserialize(ref_dict["conversation"])
        if ref_dict.get("user"):
            u = ref_dict["user"]
            ref.user = ChannelAccount(id=u["id"], name=u.get("name"), aad_object_id=u.get("aad_object_id"))
        return ref
    except Exception as e:
        logger.warning(f"Could not deserialize conversation ref: {e}")
        return None
