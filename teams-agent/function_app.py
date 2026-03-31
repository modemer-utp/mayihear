"""
Azure Functions entry point.
HTTP triggers:
  POST /api/messages  — Teams Bot Framework (chat messages)
  POST /webhook       — Graph API change notifications (transcript ready)
  GET  /health        — health check
Service Bus trigger:
  process_meeting_sb  — processes one meeting end-to-end (fetch + insights + notify)
Timer triggers:
  poll_transcripts    — every 5 min, enqueues new transcripts to Service Bus
  keep_warm           — every 4 min, pings /health to prevent cold starts
  renew_webhook       — every 50 min, keeps Graph subscription alive
"""
import json
import logging
import os
import sys
import asyncio
import datetime
import threading
import requests

import azure.functions as func
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity

# Add src/ to path so pipeline/bot/tools are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import bot as bot_module
from bot import MayiHearBot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Azure Functions app ───────────────────────────────────────────────────────
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ── Bot Framework setup ───────────────────────────────────────────────────────
adapter = BotFrameworkAdapter(BotFrameworkAdapterSettings(
    app_id=os.environ.get("BOT_ID", ""),
    app_password=os.environ.get("BOT_PASSWORD", ""),
    channel_auth_tenant=os.environ.get("BOT_TENANT_ID", ""),
))
bot = MayiHearBot()
bot_module.set_adapter(adapter)

GRAPH_WEBHOOK_SECRET = os.environ.get("GRAPH_WEBHOOK_SECRET", "mayihear-secret")
SB_QUEUE = "meetings"


async def _on_error(context: TurnContext, error: Exception):
    logger.exception("Bot turn error", exc_info=error)
    await context.send_activity("Ocurrió un error interno.")

adapter.on_turn_error = _on_error


# ── Service Bus helpers ───────────────────────────────────────────────────────

def _enqueue_meeting(meeting_id: str, transcript_id: str, organizer_email: str, subject: str):
    """Push one meeting onto the Service Bus queue for reliable async processing."""
    conn = os.environ.get("SERVICEBUS_CONNECTION_STRING", "")
    if not conn:
        logger.warning("SERVICEBUS_CONNECTION_STRING not set — processing inline (dev mode)")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(bot.process_meeting_webhook({
            "meetingId": meeting_id,
            "transcriptId": transcript_id,
            "organizerEmail": organizer_email,
            "subject": subject,
        }))
        loop.close()
        return
    from azure.servicebus import ServiceBusClient, ServiceBusMessage as SBMsg
    with ServiceBusClient.from_connection_string(conn) as client:
        with client.get_queue_sender(SB_QUEUE) as sender:
            sender.send_messages(SBMsg(json.dumps({
                "meetingId": meeting_id,
                "transcriptId": transcript_id,
                "organizerEmail": organizer_email,
                "subject": subject,
            })))
    logger.info(f"Enqueued meeting '{subject}' → Service Bus")


# ── Route: Teams chat messages ────────────────────────────────────────────────

@app.route(route="api/messages", methods=["POST"])
async def teams_messages(req: func.HttpRequest) -> func.HttpResponse:
    if "application/json" not in req.headers.get("Content-Type", ""):
        return func.HttpResponse(status_code=415)

    try:
        body = req.get_json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")

        invoke_response = await adapter.process_activity(activity, auth_header, bot.on_turn)
        if invoke_response:
            return func.HttpResponse(
                body=json.dumps(invoke_response.body),
                status_code=invoke_response.status,
                mimetype="application/json",
            )
        return func.HttpResponse(status_code=201)
    except Exception as e:
        logger.exception("teams_messages error")
        return func.HttpResponse(body=str(e), status_code=500)


# ── Route: Graph API change notifications ─────────────────────────────────────

@app.route(route="webhook", methods=["POST"])
async def graph_webhook(req: func.HttpRequest) -> func.HttpResponse:
    # Validation handshake — echo back the token
    validation_token = req.params.get("validationToken")
    if validation_token:
        logger.info("Graph webhook validation handshake")
        return func.HttpResponse(body=validation_token, status_code=200, mimetype="text/plain")

    try:
        body = req.get_json()
    except Exception:
        return func.HttpResponse(status_code=400, body="Invalid JSON")

    # Handle lifecycle notifications (reauthorizationRequired, subscriptionRemoved, missed)
    lifecycle_events = [n for n in body.get("value", []) if n.get("lifecycleEvent")]
    if lifecycle_events:
        for event in lifecycle_events:
            evt_type = event.get("lifecycleEvent")
            logger.info(f"Graph lifecycle event: {evt_type} for subscription {event.get('subscriptionId')}")
            if evt_type in ("reauthorizationRequired", "subscriptionRemoved"):
                def _bg_renew():
                    try:
                        _renew_or_create_subscription(_graph_token())
                    except Exception:
                        logger.exception("Background subscription renewal failed")
                threading.Thread(target=_bg_renew, daemon=True).start()
        return func.HttpResponse(status_code=202)

    # Enqueue each notification to Service Bus — respond to Graph within 5s
    organizer = os.environ.get("ORGANIZER_TEAMS_MAIL", "")
    for notification in body.get("value", []):
        if notification.get("clientState") != GRAPH_WEBHOOK_SECRET:
            logger.warning("clientState mismatch — skipping")
            continue

        resource_data = notification.get("resourceData", {})
        resource_url = notification.get("resource", "")  # e.g. /users/{uid}/onlineMeetings/{mid}/transcripts/{tid}

        # Primary: from resourceData fields
        meeting_id = resource_data.get("meetingId")
        transcript_id = resource_data.get("id")

        # Fallback: parse from resource URL  /users/.../onlineMeetings/{mid}/transcripts/{tid}
        if not meeting_id or not transcript_id:
            import re
            m = re.search(r"onlineMeetings/([^/]+)/transcripts/([^/?]+)", resource_url)
            if m:
                meeting_id = meeting_id or m.group(1)
                transcript_id = transcript_id or m.group(2)

        subject = resource_data.get("subject") or "Reunión Teams"
        logger.info(f"Graph webhook notification — resource: {resource_url} | meetingId: {meeting_id} | transcriptId: {transcript_id}")

        if meeting_id and transcript_id:
            threading.Thread(
                target=_enqueue_meeting,
                args=(meeting_id, transcript_id, organizer, subject),
                daemon=True,
            ).start()
        else:
            logger.warning(f"Could not extract meetingId/transcriptId from notification — skipping. resourceData: {resource_data}")

    return func.HttpResponse(status_code=202)


# ── Route: health check ───────────────────────────────────────────────────────

@app.route(route="health", methods=["GET"])
async def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("ok", status_code=200)


# ── Service Bus trigger: process one meeting ──────────────────────────────────

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="meetings",
    connection="SERVICEBUS_CONNECTION_STRING",
)
async def process_meeting_sb(msg: func.ServiceBusMessage) -> None:
    """
    Triggered by Service Bus when a meeting is enqueued.
    Fetch transcript → generate insights → notify user in Teams.
    On failure, Service Bus auto-retries (default 10x) then moves to dead-letter queue.
    """
    payload = json.loads(msg.get_body().decode())
    subject = payload.get("subject", "?")
    logger.info(f"SB trigger: processing '{subject}'")
    try:
        result = await bot.process_meeting_webhook(payload)
        logger.info(f"SB pipeline result: {result}")
    except Exception:
        logger.exception(f"SB pipeline failed for '{subject}'")
        raise  # Re-raise → Service Bus retries, then dead-letter


# ── Graph API / subscription helpers ─────────────────────────────────────────

GRAPH_API    = "https://graph.microsoft.com/v1.0"
WEBHOOK_URL  = f"https://{os.environ.get('BOT_DOMAIN', 'mayihear-agent.azurewebsites.net')}/api/webhook"
CLIENT_STATE = os.environ.get("GRAPH_WEBHOOK_SECRET", "mayihear-secret")


def _graph_token() -> str:
    tenant = os.environ["AZURE_TENANT_ID"]
    r = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["AZURE_CLIENT_ID"],
            "client_secret": os.environ["AZURE_CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _get_organizer_emails() -> list:
    """Return list of organizer emails from env. Supports comma-separated ORGANIZER_EMAILS (new) or single ORGANIZER_TEAMS_MAIL (legacy)."""
    raw = os.environ.get("ORGANIZER_EMAILS", os.environ.get("ORGANIZER_TEAMS_MAIL", ""))
    return [e.strip() for e in raw.split(",") if e.strip()]


def _renew_or_create_subscription(token: str):
    """Renew or create Graph subscriptions for all configured organizers."""
    for email in _get_organizer_emails():
        try:
            _renew_or_create_subscription_for(token, email)
        except Exception:
            logger.exception(f"Failed to renew subscription for {email}")


def _renew_or_create_subscription_for(token: str, organizer: str):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    expiry = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=59)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # Resolve user GUID
    uid_resp = requests.get(f"{GRAPH_API}/users/{organizer}?$select=id", headers=headers)
    uid_resp.raise_for_status()
    uid = uid_resp.json()["id"]

    # Find existing subscription for this specific user (match by UID in resource URL)
    subs = requests.get(f"{GRAPH_API}/subscriptions", headers=headers).json().get("value", [])
    for sub in subs:
        if uid in sub.get("resource", ""):
            r = requests.patch(
                f"{GRAPH_API}/subscriptions/{sub['id']}",
                json={"expirationDateTime": expiry},
                headers=headers,
            )
            if r.status_code == 200:
                logger.info(f"Webhook subscription renewed for {organizer} → expires {expiry}")
                return
            logger.warning(f"Renew failed ({r.status_code}) for {organizer}, recreating...")
            requests.delete(f"{GRAPH_API}/subscriptions/{sub['id']}", headers=headers)
            break

    body = {
        "changeType": "created",
        "notificationUrl": WEBHOOK_URL,
        "lifecycleNotificationUrl": WEBHOOK_URL,
        "resource": f"/users/{uid}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{uid}')",
        "expirationDateTime": expiry,
        "clientState": CLIENT_STATE,
    }
    r = requests.post(f"{GRAPH_API}/subscriptions", json=body, headers=headers)
    r.raise_for_status()
    logger.info(f"Webhook subscription created for {organizer} → expires {expiry}")


# ── Module-level processed IDs — seeded from blob once per process lifetime ───
_processed_ids: set = set()
_processed_ids_ready = False


def _load_processed_ids_once():
    global _processed_ids, _processed_ids_ready
    if not _processed_ids_ready:
        from tools.state_store import load_processed_ids
        _processed_ids = load_processed_ids()
        _processed_ids_ready = True
        logger.info(f"Loaded {len(_processed_ids)} processed transcript IDs from blob")


# ── Timer: poll for new transcripts every 5 min (fallback for webhook) ────────

@app.timer_trigger(schedule="0 */5 * * * *", arg_name="poll_timer", run_on_startup=True)
def poll_transcripts(poll_timer: func.TimerRequest) -> None:
    """Polls Graph API every 5 min for all configured organizers. Enqueues new transcripts."""
    global _processed_ids

    _load_processed_ids_once()

    organizers = _get_organizer_emails()
    logger.info(f"Polling for new transcripts ({len(organizers)} organizer(s))...")

    try:
        token = _graph_token()
        headers = {"Authorization": f"Bearer {token}"}
        from tools.state_store import save_processed_ids

        for organizer in organizers:
            try:
                uid = requests.get(
                    f"{GRAPH_API}/users/{organizer}?$select=id", headers=headers
                ).json()["id"]

                url = f"{GRAPH_API}/users/{uid}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{uid}')"
                r = requests.get(url, headers=headers)
                if r.status_code != 200:
                    logger.warning(f"getAllTranscripts returned {r.status_code} for {organizer}")
                    continue

                transcripts = r.json().get("value", [])
                new_found = [t for t in transcripts if t.get("id") and t["id"] not in _processed_ids]

                if not new_found:
                    logger.info(f"Poll [{organizer}]: {len(transcripts)} transcript(s) checked, none new")
                    continue

                for t in new_found:
                    tid = t["id"]
                    meeting_id = t.get("meetingId") or ""
                    subject = t.get("subject") or "Reunión Teams"
                    logger.info(f"New transcript [{organizer}]: '{subject}' id={tid[:40]}...")

                    # Mark processed FIRST — prevents re-queuing even if enqueue fails
                    _processed_ids.add(tid)
                    save_processed_ids(_processed_ids)

                    _enqueue_meeting(meeting_id, tid, organizer, subject)

            except Exception:
                logger.exception(f"poll_transcripts failed for {organizer}")

    except Exception:
        logger.exception("poll_transcripts: failed to obtain Graph token")


# ── Timer: keep-warm ping every 4 min ────────────────────────────────────────

@app.timer_trigger(schedule="0 */4 * * * *", arg_name="warmup_timer", run_on_startup=True)
def keep_warm(warmup_timer: func.TimerRequest) -> None:
    """Pings /api/health every 4 minutes to prevent cold starts."""
    try:
        domain = os.environ.get("BOT_DOMAIN", "mayihear-agent.azurewebsites.net")
        requests.get(f"https://{domain}/api/health", timeout=10)
        logger.info("Keep-warm ping sent")
    except Exception:
        pass


# ── Timer: renew Graph webhook subscription every 50 min ─────────────────────

@app.timer_trigger(schedule="0 */50 * * * *", arg_name="timer", run_on_startup=True)
def renew_webhook(timer: func.TimerRequest) -> None:
    """Keeps the Graph change notification subscription alive. Runs every 50 min."""
    logger.info("Timer: renewing Graph webhook subscription...")
    try:
        token = _graph_token()
        _renew_or_create_subscription(token)
    except Exception:
        logger.exception("Failed to renew Graph webhook subscription")
