"""
Azure Functions entry point.
HTTP triggers:
  POST /api/messages  — Teams Bot Framework (chat messages)
  POST /webhook       — Graph API change notifications (transcript ready)
  GET  /health        — health check
Service Bus trigger:
  process_meeting_sb  — processes one meeting end-to-end (fetch + insights + notify)
Timer triggers:
  keep_warm           — every 4 min, pings /health to prevent cold starts
  renew_webhook       — every 50 min, keeps Graph subscription alive

Polling removed: Graph webhook is the sole trigger.
The webhook fires on callTranscript "created" (= transcription started, not meeting ended).
We guard against mid-meeting notifications by checking endDateTime before enqueuing.
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

def _enqueue_meeting(meeting_id: str, transcript_id: str, organizer_email: str, subject: str, scheduled_at=None):
    """
    Push one meeting onto the Service Bus queue.
    scheduled_at: datetime (UTC) for delayed delivery, or None for immediate.
    """
    import datetime
    conn = os.environ.get("SERVICEBUS_CONNECTION_STRING", "")
    if not conn:
        if scheduled_at and scheduled_at > datetime.datetime.now(datetime.timezone.utc):
            delay_s = (scheduled_at - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            logger.info(f"No SB conn — sleeping {delay_s:.0f}s before inline processing (dev mode)")
            import time; time.sleep(min(delay_s, 300))
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
    msg = SBMsg(json.dumps({
        "meetingId": meeting_id,
        "transcriptId": transcript_id,
        "organizerEmail": organizer_email,
        "subject": subject,
    }))
    if scheduled_at:
        msg.scheduled_enqueue_time_utc = scheduled_at
        logger.info(f"Scheduling meeting '{subject}' → Service Bus at {scheduled_at.isoformat()}")
    with ServiceBusClient.from_connection_string(conn) as client:
        with client.get_queue_sender(SB_QUEUE) as sender:
            sender.send_messages(msg)
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
        resource_url = notification.get("resource", "")

        # ── callRecord notification ───────────────────────────────────────────
        odata_type = resource_data.get("@odata.type", "")
        if "#microsoft.graph.callRecord" in odata_type or resource_url.startswith("/communications/callRecords"):
            call_record_id = resource_data.get("id")
            if call_record_id:
                logger.info(f"callRecord notification received: {call_record_id}")
                threading.Thread(
                    target=_handle_call_record,
                    args=(call_record_id,),
                    daemon=True,
                ).start()
            continue

        # ── transcript notification (existing flow) ───────────────────────────

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

        if not meeting_id or not transcript_id:
            logger.warning(f"Could not extract meetingId/transcriptId — skipping. resourceData: {resource_data}")
            continue

        # Deduplicate: skip if already processed (by transcript ID or meeting ID)
        _load_processed_ids_once()
        if transcript_id in _processed_ids:
            logger.info(f"Transcript {transcript_id[:30]}... already processed — skipping")
            continue
        if meeting_id in _processed_meeting_ids:
            logger.info(f"Meeting {meeting_id[:30]}... already enqueued (different transcript) — skipping duplicate")
            continue

        # Mark meeting as seen immediately to block concurrent second transcripts
        _processed_meeting_ids.add(meeting_id)

        # Fire-and-forget: validate meeting is over before enqueuing
        threading.Thread(
            target=_validate_and_enqueue,
            args=(meeting_id, transcript_id, organizer, subject),
            daemon=True,
        ).start()

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
    """Renew or create Graph subscriptions: per-user transcripts + tenant-wide callRecords."""
    for email in _get_organizer_emails():
        try:
            _renew_or_create_subscription_for(token, email)
        except Exception:
            logger.exception(f"Failed to renew transcript subscription for {email}")
    try:
        _renew_or_create_callrecord_subscription(token)
    except Exception:
        logger.exception("Failed to renew callRecords subscription")


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


def _renew_or_create_callrecord_subscription(token: str):
    """
    Create or renew a single tenant-wide callRecords subscription.
    Fires when any call in the tenant ends — we filter by organizer in _handle_call_record.
    Max expiry for callRecords is 4320 minutes (~3 days), renewed every 30 min by the timer.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    expiry = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=4229)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    subs = requests.get(f"{GRAPH_API}/subscriptions", headers=headers).json().get("value", [])
    for sub in subs:
        if sub.get("resource") == "/communications/callRecords":
            r = requests.patch(
                f"{GRAPH_API}/subscriptions/{sub['id']}",
                json={"expirationDateTime": expiry},
                headers=headers,
            )
            if r.status_code == 200:
                logger.info(f"callRecords subscription renewed → expires {expiry}")
                return
            logger.warning(f"callRecords renew failed ({r.status_code}) — recreating")
            requests.delete(f"{GRAPH_API}/subscriptions/{sub['id']}", headers=headers)
            break

    body = {
        "changeType": "created",
        "notificationUrl": WEBHOOK_URL,
        "lifecycleNotificationUrl": WEBHOOK_URL,
        "resource": "/communications/callRecords",
        "expirationDateTime": expiry,
        "clientState": CLIENT_STATE,
    }
    r = requests.post(f"{GRAPH_API}/subscriptions", json=body, headers=headers)
    r.raise_for_status()
    logger.info(f"callRecords subscription created → expires {expiry}")


# ── Processed IDs — deduplicate webhook notifications within a process lifetime ──
_processed_ids: set = set()          # transcript IDs
_processed_meeting_ids: set = set()  # meeting IDs — prevents dual-transcript duplicates
_processed_ids_ready = False

# ── Pending transcripts waiting for their callRecord ─────────────────────────
# organizer_email (lower) → list of {meeting_id, transcript_id, subject, calendar_end_dt, detected_at}
_pending_transcripts: dict = {}


def _load_processed_ids_once():
    global _processed_ids, _processed_ids_ready
    if not _processed_ids_ready:
        from tools.state_store import load_processed_ids
        _processed_ids = load_processed_ids()
        _processed_ids_ready = True
        logger.info(f"Loaded {len(_processed_ids)} processed transcript IDs from blob")


def _validate_and_enqueue(meeting_id: str, transcript_id: str, organizer: str, subject: str):
    """
    Called after a Graph webhook notification or by the fallback timer.

    Guard rule: endDateTime is the ONLY reliable signal.
    - endDateTime unknown       → schedule 10 min from now as safe fallback
    - endDateTime in future     → meeting still running → schedule at endDateTime + TRANSCRIPT_BUFFER
    - endDateTime just passed   → meeting ended recently → schedule at endDateTime + TRANSCRIPT_BUFFER
    - endDateTime long past     → safe to process soon → schedule 2 min from now

    TRANSCRIPT_BUFFER = 5 min: Teams takes ~5 min after meeting end to finalize the
    full transcript. Fetching at +1 min captures only what was transcribed in that
    first minute, losing the rest of the meeting.
    """
    import datetime
    from tools.state_store import save_processed_ids
    from tools.graph_client import get_token as _gc_token, get_meeting_details

    TRANSCRIPT_BUFFER = datetime.timedelta(minutes=5)

    try:
        token = _gc_token()
        now = datetime.datetime.now(datetime.timezone.utc)
        details = get_meeting_details(token, organizer, meeting_id)
        end_dt_str = details.get("endDateTime")
        start_dt_str = details.get("startDateTime")

        # Append start time (Peru UTC-5) to subject for disambiguation
        if start_dt_str:
            try:
                start_dt = datetime.datetime.fromisoformat(start_dt_str.replace("Z", "+00:00"))
                peru_time = start_dt - datetime.timedelta(hours=5)
                subject = f"{subject} ({peru_time.strftime('%I:%M %p')})"
            except Exception:
                pass

        if end_dt_str is None:
            # No endDateTime — can't tell if meeting is over, wait 10 min
            scheduled_at = now + datetime.timedelta(minutes=10)
            logger.info(f"Meeting '{subject}': no endDateTime — scheduling in 10 min")
        else:
            end_dt = datetime.datetime.fromisoformat(end_dt_str.replace("Z", "+00:00"))
            ideal = end_dt + TRANSCRIPT_BUFFER  # always wait buffer after scheduled end
            if ideal > now:
                # Either meeting is still running, or it just ended and Teams hasn't finalized yet
                scheduled_at = ideal
                logger.info(
                    f"Meeting '{subject}': scheduling at {ideal.isoformat()} "
                    f"(endDateTime {end_dt_str} + {TRANSCRIPT_BUFFER.seconds // 60} min buffer)"
                )
            else:
                # Meeting ended long enough ago — process in 2 min as a minimal safety margin
                scheduled_at = now + datetime.timedelta(minutes=2)
                logger.info(
                    f"Meeting '{subject}': ended at {end_dt_str}, buffer already elapsed — "
                    f"scheduling in 2 min"
                )

        _processed_ids.add(transcript_id)
        _processed_meeting_ids.add(meeting_id)
        save_processed_ids(_processed_ids)

        # Register in pending_transcripts so callRecord can override the schedule
        org_key = organizer.lower()
        calendar_end_dt = (
            datetime.datetime.fromisoformat(end_dt_str.replace("Z", "+00:00"))
            if end_dt_str else None
        )
        _pending_transcripts.setdefault(org_key, []).append({
            "meeting_id": meeting_id,
            "transcript_id": transcript_id,
            "subject": subject,
            "calendar_end_dt": calendar_end_dt,
            "detected_at": now,
        })

        _enqueue_meeting(meeting_id, transcript_id, organizer, subject, scheduled_at=scheduled_at)

    except Exception:
        logger.exception(f"_validate_and_enqueue failed for '{subject}'")


def _handle_call_record(call_record_id: str):
    """
    Process a callRecord notification to get the actual meeting end time.
    Matches the callRecord to a pending transcript (stored by _validate_and_enqueue)
    and schedules processing with the real endDateTime instead of the calendar one.

    Handles two cases:
    - Normal meeting (ended on time): callRecord may arrive before the calendar-based
      SB message fires → preempts it with a more accurate schedule (+3 min).
    - Meeting ran over: callRecord arrives after calendar-based processing already ran
      with partial transcript → clears the dedup flag and re-queues at actual end +3 min.
    """
    import datetime
    from tools.graph_client import get_token as _gc_token, get_call_record
    from tools.graph import resolve_email_from_aad_id

    try:
        token = _gc_token()
        record = get_call_record(token, call_record_id)
        if not record:
            logger.warning(f"callRecord {call_record_id}: could not fetch — skipping")
            return

        actual_end_str = record.get("endDateTime")
        actual_start_str = record.get("startDateTime")
        organizer_aad_id = record.get("organizer", {}).get("user", {}).get("id", "")

        if not actual_end_str or not organizer_aad_id:
            logger.info(f"callRecord {call_record_id}: missing end time or organizer — skipping")
            return

        actual_end_dt = datetime.datetime.fromisoformat(actual_end_str.replace("Z", "+00:00"))
        actual_start_dt = (
            datetime.datetime.fromisoformat(actual_start_str.replace("Z", "+00:00"))
            if actual_start_str else None
        )

        # Resolve organizer AAD ID → email
        organizer_email = resolve_email_from_aad_id(organizer_aad_id)
        if not organizer_email:
            logger.info(f"callRecord {call_record_id}: could not resolve organizer — skipping")
            return

        organizer_email = organizer_email.lower()
        if organizer_email not in [e.lower() for e in _get_organizer_emails()]:
            logger.info(f"callRecord {call_record_id}: organizer {organizer_email} not monitored — skipping")
            return

        logger.info(f"callRecord for {organizer_email}: actual end={actual_end_str}")

        # Find matching pending transcript by time window
        now = datetime.datetime.now(datetime.timezone.utc)
        pending_list = _pending_transcripts.get(organizer_email, [])
        matched = None
        for entry in pending_list:
            detected = entry["detected_at"]
            window_start = (actual_start_dt - datetime.timedelta(minutes=10)) if actual_start_dt else (detected - datetime.timedelta(hours=2))
            window_end = actual_end_dt + datetime.timedelta(minutes=15)
            if window_start <= detected <= window_end:
                matched = entry
                break

        if not matched:
            logger.info(f"callRecord {call_record_id}: no pending transcript found for {organizer_email} — skipping")
            return

        meeting_id   = matched["meeting_id"]
        transcript_id = matched["transcript_id"]
        subject       = matched["subject"]
        calendar_end  = matched.get("calendar_end_dt")

        # Remove from pending now that it's been claimed
        _pending_transcripts[organizer_email] = [
            e for e in pending_list if e["transcript_id"] != transcript_id
        ]

        # If the meeting ran significantly over the calendar end, the calendar-based
        # SB message may have already fetched a partial transcript — re-queue with the
        # full transcript now available.
        ran_over = (
            calendar_end is not None and
            actual_end_dt > calendar_end + datetime.timedelta(minutes=5)
        )
        if ran_over and transcript_id in _processed_ids:
            logger.info(
                f"callRecord: '{subject}' ran {int((actual_end_dt - calendar_end).total_seconds() // 60)} min "
                f"over schedule — clearing dedup and re-queuing for full transcript"
            )
            _processed_ids.discard(transcript_id)
            _processed_meeting_ids.discard(meeting_id)
        elif transcript_id in _processed_ids:
            logger.info(f"callRecord: '{subject}' already processed on time — no action needed")
            return

        # Schedule at actual end + 3 min (Teams needs ~3 min to flush final VTT after call ends)
        scheduled_at = actual_end_dt + datetime.timedelta(minutes=3)
        if scheduled_at <= now:
            scheduled_at = now + datetime.timedelta(minutes=1)

        logger.info(f"callRecord trigger: queuing '{subject}' at {scheduled_at.isoformat()}")
        _enqueue_meeting(meeting_id, transcript_id, organizer_email, subject, scheduled_at=scheduled_at)

    except Exception:
        logger.exception(f"_handle_call_record failed for {call_record_id}")


# ── Timer: fallback transcript check every 2 min ─────────────────────────────

@app.timer_trigger(schedule="0 */2 * * * *", arg_name="catchup_timer", run_on_startup=False)
def check_missed_transcripts(catchup_timer: func.TimerRequest) -> None:
    """
    Fallback for when Graph webhook misses a notification (e.g. subscription gap on redeploy).
    Checks only the most recent transcript per organizer.
    Only processes if:
      1. Not already in _processed_ids (dedup)
      2. Meeting endDateTime is in the past (never notifies during an active meeting)
    """
    import datetime
    _load_processed_ids_once()

    organizers = _get_organizer_emails()
    try:
        token = _graph_token()
        headers = {"Authorization": f"Bearer {token}"}
        now = datetime.datetime.now(datetime.timezone.utc)

        for organizer in organizers:
            try:
                uid_resp = requests.get(f"{GRAPH_API}/users/{organizer}?$select=id", headers=headers)
                uid_resp.raise_for_status()
                uid = uid_resp.json()["id"]

                url = (
                    f"{GRAPH_API}/users/{uid}/onlineMeetings"
                    f"/getAllTranscripts(meetingOrganizerUserId='{uid}')"
                )
                resp = requests.get(url, headers=headers)
                if resp.status_code != 200:
                    continue

                transcripts = resp.json().get("value", [])
                if not transcripts:
                    continue

                # Only check the single most recent transcript
                latest = max(transcripts, key=lambda t: t.get("createdDateTime", ""))
                tid = latest.get("id")
                mid = latest.get("meetingId", "")

                if not tid or tid in _processed_ids or mid in _processed_meeting_ids:
                    continue  # already handled

                # Guard: only process if meeting has ended AND transcript buffer has elapsed
                from tools.graph_client import get_meeting_details as _gmd
                details = _gmd(token, organizer, mid)
                end_dt_str = details.get("endDateTime", "")

                if not end_dt_str:
                    logger.info(f"Catchup [{organizer}]: no endDateTime — skipping")
                    continue

                end_dt = datetime.datetime.fromisoformat(end_dt_str.replace("Z", "+00:00"))
                transcript_ready_at = end_dt + datetime.timedelta(minutes=5)
                if transcript_ready_at > now:
                    logger.info(
                        f"Catchup [{organizer}]: waiting for transcript finalization until "
                        f"{transcript_ready_at.isoformat()} — skipping"
                    )
                    continue

                # Raw subject only — _validate_and_enqueue appends the start time
                subject = details.get("subject") or "Reunión Teams"

                # Mark as processed NOW — before spawning thread — to prevent
                # race condition where the next 2-min timer fires before the
                # background thread adds the ID to _processed_ids
                from tools.state_store import save_processed_ids
                _processed_ids.add(tid)
                _processed_meeting_ids.add(mid)
                save_processed_ids(_processed_ids)

                logger.info(f"Catchup [{organizer}]: found unprocessed transcript '{subject}' — enqueuing")
                threading.Thread(
                    target=_validate_and_enqueue,
                    args=(mid, tid, organizer, subject),
                    daemon=True,
                ).start()

            except Exception:
                logger.exception(f"check_missed_transcripts failed for {organizer}")

    except Exception:
        logger.exception("check_missed_transcripts: failed to obtain Graph token")


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

@app.timer_trigger(schedule="0 */30 * * * *", arg_name="timer", run_on_startup=True)
def renew_webhook(timer: func.TimerRequest) -> None:
    """Keeps the Graph change notification subscription alive. Runs every 30 min."""
    logger.info("Timer: renewing Graph webhook subscription...")
    try:
        token = _graph_token()
        _renew_or_create_subscription(token)
    except Exception:
        logger.exception("Failed to renew Graph webhook subscription")
