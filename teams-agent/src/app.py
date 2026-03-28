"""
Entry point — aiohttp server exposing:
  POST /api/messages  — Teams Bot Framework endpoint (chat messages)
  POST /webhook       — Graph API change notifications (meeting transcript ready)
  GET  /health        — health check
"""
import json
import logging
import os
from aiohttp import web
from aiohttp.web import Request, Response

from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity

from bot import MayiHearBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ── Bot Framework setup ───────────────────────────────────────────────────────

settings = BotFrameworkAdapterSettings(
    app_id=os.environ.get("BOT_ID", ""),
    app_password=os.environ.get("BOT_PASSWORD", ""),
)
adapter = BotFrameworkAdapter(settings)
bot = MayiHearBot()

GRAPH_WEBHOOK_SECRET = os.environ.get("GRAPH_WEBHOOK_SECRET", "mayihear-secret")


async def on_error(context: TurnContext, error: Exception):
    logger.exception("Unhandled error in bot turn", exc_info=error)
    await context.send_activity("Ocurrió un error interno. Por favor intenta de nuevo.")


adapter.on_turn_error = on_error


# ── Routes ───────────────────────────────────────────────────────────────────

async def health(req: Request) -> Response:
    return Response(text="ok")


async def messages(req: Request) -> Response:
    """Teams Bot Framework — handles chat messages."""
    if "application/json" not in req.headers.get("Content-Type", ""):
        return Response(status=415)

    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    invoke_response = await adapter.process_activity(activity, auth_header, bot.on_turn)
    if invoke_response:
        return Response(
            status=invoke_response.status,
            body=json.dumps(invoke_response.body),
            content_type="application/json",
        )
    return Response(status=201)


async def webhook(req: Request) -> Response:
    """
    Graph API change notifications.

    Two cases:
    1. Validation handshake — Graph sends ?validationToken=... on subscription creation.
       Must echo it back as plain text with 200.
    2. Real notification — JSON payload with transcript info.
    """
    # Validation handshake
    validation_token = req.rel_url.query.get("validationToken")
    if validation_token:
        logger.info("Graph webhook validation handshake received")
        return Response(text=validation_token, content_type="text/plain")

    # Real notification
    try:
        body = await req.json()
    except Exception:
        return Response(status=400, text="Invalid JSON")

    # Verify clientState matches our secret
    for notification in body.get("value", []):
        if notification.get("clientState") != GRAPH_WEBHOOK_SECRET:
            logger.warning("clientState mismatch — ignoring notification")
            continue

        logger.info(f"Graph notification received: {notification.get('resource')}")

        # Process asynchronously so we respond to Graph within 5s
        req.app.loop.create_task(_process_notification(notification))

    # Graph requires 202 within 5 seconds
    return Response(status=202)


async def _process_notification(notification: dict):
    try:
        result = await bot.process_meeting_webhook(notification)
        logger.info(f"Pipeline result: {result}")
    except Exception:
        logger.exception("Pipeline failed for notification")


# ── App setup ─────────────────────────────────────────────────────────────────

app = web.Application()
app.router.add_get("/health", health)
app.router.add_post("/api/messages", messages)
app.router.add_post("/webhook", webhook)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3978))
    logger.info(f"MayiHear agent starting on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)
