"""
Teams activity handler with conversational state machine:
  - Webhook fires → insights shown to user → confirm / regenerate / cancel
  - Board selection: user can choose which Monday board to publish to
  - Proactive messaging: bot initiates conversation when meeting is processed
  - State persisted in Azure Table Storage — survives redeploys + multi-instance scaling
"""
import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from botbuilder.core import ActivityHandler, TurnContext, MessageFactory
from botbuilder.schema import ConversationReference

import pipeline
from tools.monday import list_boards, create_meeting_item
from tools.llm import generate_insights, format_insights_for_monday
from tools.state_store import save_conversation_ref, load_conversation_ref
from tools.table_state import get_conv_state, set_conv_state

_executor = ThreadPoolExecutor(max_workers=4)
logger = logging.getLogger(__name__)

# ── Global adapter reference (set from function_app.py after adapter is created) ──
_adapter = None

def set_adapter(adapter):
    global _adapter
    _adapter = adapter

# ── In-memory refs + last processed (lightweight, acceptable to lose on restart) ──
_conv_refs: dict = {}
_last_processed: dict = {}


class MayiHearBot(ActivityHandler):

    # ── Incoming messages ──────────────────────────────────────────────────────

    async def on_message_activity(self, turn_context: TurnContext):
        _save_ref(turn_context)

        conv_id = turn_context.activity.conversation.id
        text = (turn_context.activity.text or "").strip().lower()
        state = get_conv_state(conv_id)
        phase = state.get("phase")

        # Route by current conversation phase first
        if phase == "awaiting_confirmation":
            await self._handle_confirmation(turn_context, text, state, conv_id)
            return

        if phase == "awaiting_board":
            await self._handle_board_choice(turn_context, text, state, conv_id)
            return

        # Top-level commands
        if any(w in text for w in ("boards", "tablero", "board")):
            await self._cmd_show_boards(turn_context, conv_id, state)

        elif "status" in text:
            await turn_context.send_activity(
                MessageFactory.text("✅ MayiHear está activo. Procesando reuniones automáticamente cuando terminan.")
            )

        elif "last meeting" in text or "última reunión" in text:
            await self._cmd_last_meeting(turn_context)

        else:
            board_name = state.get("selected_board_name", os.environ.get("MONDAY_BOARD_ID", "Monday"))
            await turn_context.send_activity(
                MessageFactory.text(
                    "Hola! Soy MayiHear. Proceso automáticamente las reuniones de Teams y publico insights en Monday.\n\n"
                    f"📌 Tablero actual: **{board_name}**\n\n"
                    "Comandos:\n"
                    "• **status** — estado del agente\n"
                    "• **boards** — ver y cambiar tablero de Monday\n"
                    "• **last meeting** — insights de la última reunión procesada"
                )
            )

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "Hola! Soy MayiHear 👋\n\n"
                        "Procesaré automáticamente tus reuniones de Teams y publicaré los insights en Monday.\n\n"
                        "Usa **boards** para elegir el tablero donde publicar."
                    )
                )

    # ── Commands ───────────────────────────────────────────────────────────────

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
            marker = " ✅" if b["id"] == state.get("selected_board_id") else ""
            lines.append(f"**{i}.** {b['name']}{marker}")
        lines.append("\nResponde con el **número** del tablero donde quieres publicar los insights.")

        set_conv_state(conv_id, {**state, "phase": "awaiting_board", "boards": boards})
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

    # ── State: board selection ─────────────────────────────────────────────────

    async def _handle_board_choice(self, turn_context: TurnContext, text: str, state: dict, conv_id: str):
        boards = state.get("boards", [])
        try:
            idx = int(text.strip()) - 1
            if 0 <= idx < len(boards):
                chosen = boards[idx]
                set_conv_state(conv_id, {
                    **state,
                    "phase": None,
                    "selected_board_id": chosen["id"],
                    "selected_board_name": chosen["name"],
                })
                await turn_context.send_activity(
                    MessageFactory.text(f"✅ Tablero seleccionado: **{chosen['name']}**. Los próximos insights se publicarán aquí.")
                )
                return
        except ValueError:
            pass
        await turn_context.send_activity(
            MessageFactory.text(f"Por favor responde con un número entre 1 y {len(boards)}.")
        )

    # ── State: insight confirmation ────────────────────────────────────────────

    async def _handle_confirmation(self, turn_context: TurnContext, text: str, state: dict, conv_id: str):
        pending = state.get("pending", {})

        if any(w in text for w in ("confirmar", "confirm", "sí", "si", "publicar", "yes")):
            board_id = state.get("selected_board_id") or os.environ.get("MONDAY_BOARD_ID")
            board_name = state.get("selected_board_name", "Monday")
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
            await turn_context.send_activity(
                MessageFactory.text(f"✅ **{pending['subject']}** publicada en **{board_name}** → item `{item_id}`")
            )
            await self._advance_queue(turn_context, state, conv_id)

        elif any(w in text for w in ("regenerar", "regenerate", "nuevo", "volver")):
            await turn_context.send_activity(MessageFactory.text("🔄 Regenerando insights con Gemini..."))
            loop = asyncio.get_event_loop()
            try:
                insights = await loop.run_in_executor(
                    _executor, generate_insights, pending["transcript_text"]
                )
                insights_text = format_insights_for_monday(insights)
            except Exception as e:
                await turn_context.send_activity(MessageFactory.text(f"❌ Error: {e}"))
                return
            new_pending = {**pending, "insights": insights, "insights_text": insights_text}
            set_conv_state(conv_id, {**state, "pending": new_pending})
            await turn_context.send_activity(
                MessageFactory.text(
                    f"🔄 **Nuevos insights — {pending['subject']}**\n\n{insights_text}\n\n"
                    "---\nResponde: **confirmar** · **regenerar** · **cancelar**"
                )
            )

        elif any(w in text for w in ("cancelar", "cancel", "no")):
            await turn_context.send_activity(
                MessageFactory.text("❌ Cancelado. Los insights no se publicaron en Monday.")
            )
            await self._advance_queue(turn_context, state, conv_id)

        else:
            await turn_context.send_activity(
                MessageFactory.text("Responde: **confirmar** para publicar · **regenerar** para nuevos insights · **cancelar**")
            )

    # ── Queue helpers ──────────────────────────────────────────────────────────

    async def _advance_queue(self, turn_context: TurnContext, state: dict, conv_id: str):
        """After resolving current meeting, start next queued one or clear phase."""
        queue = list(state.get("pending_queue", []))
        if queue:
            next_pending = queue.pop(0)
            set_conv_state(conv_id, {**state, "phase": "awaiting_confirmation", "pending": next_pending, "pending_queue": queue})
            subject = next_pending.get("subject", "Reunión")
            remaining = f" ({len(queue)} más en cola)" if queue else ""
            await turn_context.send_activity(
                MessageFactory.text(
                    f"📝 **Siguiente reunión: {subject}**{remaining}\n\n"
                    f"{next_pending['insights_text']}\n\n"
                    "---\nResponde: **confirmar** · **regenerar** · **cancelar**"
                )
            )
        else:
            set_conv_state(conv_id, {**state, "phase": None, "pending_queue": []})

    # ── Webhook / Service Bus handler ──────────────────────────────────────────

    async def process_meeting_webhook(self, payload: dict) -> str:
        """
        Called by Service Bus trigger (or webhook fallback) for each new transcript.
        Fetches transcript + generates insights, then asks organizer to confirm before posting.
        Falls back to auto-post if no conversation reference is stored yet.
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

        # Step 1+2: fetch transcript only (no Monday post yet)
        transcript_data = await loop.run_in_executor(
            _executor, pipeline.fetch_transcript,
            organizer_email, meeting_id, transcript_id, subject
        )
        # Step 3: generate insights
        result = await loop.run_in_executor(
            _executor, pipeline.generate,
            transcript_data["transcript_text"], subject
        )

        # Try proactive message to organizer for review
        ref = _get_any_ref()
        if ref and _adapter:
            msg = (
                f"📝 **Nueva reunión lista: {subject}**\n\n"
                f"{result['insights_text']}\n\n"
                "---\n"
                "¿Publicar estos insights en Monday?\n"
                "Responde: **confirmar** · **regenerar** · **cancelar**"
            )

            async def _callback(ctx: TurnContext):
                conv_id = ctx.activity.conversation.id
                state = get_conv_state(conv_id)
                if state.get("phase") == "awaiting_confirmation":
                    # Already reviewing a meeting — enqueue this one
                    queue = list(state.get("pending_queue", []))
                    queue.append(result)
                    set_conv_state(conv_id, {**state, "pending_queue": queue})
                    await ctx.send_activity(
                        MessageFactory.text(
                            f"⏳ **{subject}** procesada y en cola ({len(queue)} pendiente{'s' if len(queue) > 1 else ''}). "
                            "Termina la revisión actual primero."
                        )
                    )
                else:
                    set_conv_state(conv_id, {**state, "phase": "awaiting_confirmation", "pending": result, "pending_queue": []})
                    await ctx.send_activity(MessageFactory.text(msg))

            await _adapter.continue_conversation(ref, _callback, os.environ.get("BOT_ID", ""))
            logger.info(f"Proactive message sent for '{subject}'")
            return f"Notified user about '{subject}'"

        else:
            # No stored ref yet → auto-post as fallback
            logger.warning("No conversation reference stored — auto-posting to Monday")
            item_id = await loop.run_in_executor(
                _executor, pipeline.post_to_monday,
                subject, result["insights_text"], None
            )
            _last_processed.update({**result, "item_id": item_id})
            return f"✅ Auto-published '{subject}' → Monday item {item_id}"


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
    # Persist to blob so it survives redeploys
    try:
        ref_dict = {
            "activity_id": ref.activity_id,
            "bot": {"id": ref.bot.id, "name": ref.bot.name} if ref.bot else None,
            "channel_id": ref.channel_id,
            "conversation": ref.conversation.serialize() if ref.conversation else None,
            "locale": ref.locale,
            "service_url": ref.service_url,
            "user": {"id": ref.user.id, "name": ref.user.name, "aad_object_id": ref.user.aad_object_id} if ref.user else None,
        }
        save_conversation_ref(ref_dict)
    except Exception as e:
        logger.warning(f"Could not persist conversation ref: {e}")


def _get_any_ref() -> ConversationReference | None:
    """Return stored conversation reference — checks memory first, then blob storage."""
    # In-memory (fast path)
    ref = next(iter(_conv_refs.values()), None)
    if ref:
        return ref

    # Load from persistent blob storage (survives redeploys)
    ref_dict = load_conversation_ref()
    if not ref_dict:
        return None

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
        _conv_refs["__loaded__"] = ref
        logger.info("Conversation reference restored from blob storage")
        return ref
    except Exception as e:
        logger.warning(f"Could not restore conversation ref from blob: {e}")
        return None
