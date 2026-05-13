import os
import requests

TENANT_ID = os.environ["AZURE_TENANT_ID"]
CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
GRAPH_API = "https://graph.microsoft.com/v1.0"


def get_token() -> str:
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    r = requests.post(url, data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    })
    r.raise_for_status()
    return r.json()["access_token"]


def get_user_id(token: str, email: str) -> str:
    """Resolve user email to GUID — required by transcript content endpoint."""
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH_API}/users/{email}?$select=id", headers=headers)
    r.raise_for_status()
    return r.json()["id"]


def get_transcript_content(token: str, organizer_email: str, meeting_id: str, transcript_id: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/vtt",
    }
    # Transcript content endpoint requires user GUID, not email
    user_id = get_user_id(token, organizer_email)
    r = requests.get(
        f"{GRAPH_API}/users/{user_id}/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content",
        headers=headers,
    )
    r.raise_for_status()
    return r.content.decode('utf-8')


def get_meeting_details(token: str, organizer_email: str, meeting_id: str) -> dict:
    """
    Returns dict with startDateTime, endDateTime, subject from the online meeting.
    Used to check timing and build display title.
    """
    headers = {"Authorization": f"Bearer {token}"}
    user_id = get_user_id(token, organizer_email)
    r = requests.get(
        f"{GRAPH_API}/users/{user_id}/onlineMeetings/{meeting_id}?$select=startDateTime,endDateTime,subject",
        headers=headers,
    )
    if r.status_code != 200:
        return {}
    return r.json()


def get_meeting_end_time(token: str, organizer_email: str, meeting_id: str) -> str | None:
    """Returns the meeting's endDateTime (ISO 8601 UTC) or None. Legacy helper."""
    return get_meeting_details(token, organizer_email, meeting_id).get("endDateTime")


def get_meetings(token: str, organizer_email: str) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{GRAPH_API}/users/{organizer_email}/onlineMeetings",
        headers=headers,
    )
    r.raise_for_status()
    return r.json().get("value", [])


def get_transcripts(token: str, organizer_email: str, meeting_id: str) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{GRAPH_API}/users/{organizer_email}/onlineMeetings/{meeting_id}/transcripts",
        headers=headers,
    )
    r.raise_for_status()
    return r.json().get("value", [])


def get_call_record(token: str, call_record_id: str) -> dict:
    """
    Fetch a callRecord by ID.
    Returns dict with startDateTime, endDateTime, organizer.user.id, joinWebUrl.
    Requires CallRecords.Read.All application permission.
    """
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{GRAPH_API}/communications/callRecords/{call_record_id}",
        headers=headers,
        timeout=15,
    )
    if r.status_code != 200:
        return {}
    return r.json()


def register_transcript_webhook(token: str, notification_url: str, organizer_id: str) -> dict:
    """
    Subscribe to transcript change notifications for all meetings of a user.
    notification_url must be a public HTTPS endpoint.
    Subscription is valid for 60 minutes (max for this resource) — renew periodically.
    """
    import datetime
    expiry = (datetime.datetime.utcnow() + datetime.timedelta(minutes=59)).strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "changeType": "created",
        "notificationUrl": notification_url,
        "resource": f"/users/{organizer_id}/onlineMeetings/getAllTranscripts",
        "expirationDateTime": expiry,
        "clientState": "mayihear-secret",
    }
    r = requests.post(f"{GRAPH_API}/subscriptions", json=body, headers=headers)
    r.raise_for_status()
    return r.json()
