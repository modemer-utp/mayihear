"""
Quick test to verify Graph API credentials and Teams transcript access.
Run from project root: python test_graph_api.py
"""
import requests
import base64
import json

import os
from dotenv import load_dotenv
load_dotenv("teams-agent/.env.dev")

# Credentials — loaded from teams-agent/.env.dev (never hardcode secrets)
TENANT_ID = os.environ["AZURE_TENANT_ID"]
CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
ORGANIZER_EMAIL = os.environ["ORGANIZER_TEAMS_MAIL"]

GRAPH_API = "https://graph.microsoft.com/v1.0"


def get_token():
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    print("[OK] Token obtained")
    return r.json()["access_token"]


def decode_token_roles(token):
    """Decode JWT payload to see what app roles/permissions are in the token."""
    try:
        payload_b64 = token.split(".")[1]
        # Pad base64 string
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.b64decode(payload_b64))
        roles = payload.get("roles", [])
        print(f"[INFO] App permissions in token: {roles if roles else 'none found'}")
        return roles
    except Exception as e:
        print(f"[WARN] Could not decode token: {e}")
        return []


def get_user_id(token):
    """Resolve email → AAD user GUID. Requires User.Read.All."""
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH_API}/users/{ORGANIZER_EMAIL}?$select=id", headers=headers)
    if r.status_code == 200:
        uid = r.json().get("id")
        print(f"[OK] User ID resolved: {uid}")
        return uid
    else:
        print(f"[SKIP] Could not resolve user ID ({r.status_code}) — User.Read.All may be missing")
        return None


def get_all_transcripts(token, user_ref):
    """
    Uses /getAllTranscripts OData function — lists all transcripts across all meetings.
    Requires OnlineMeetingTranscript.Read.All (app permission).
    user_ref can be GUID or UPN (email).
    """
    headers = {"Authorization": f"Bearer {token}"}
    # Try with user_ref as both the path and function parameter
    url = f"{GRAPH_API}/users/{user_ref}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{user_ref}')"
    print(f"\n[1] Trying getAllTranscripts with ref='{user_ref}'...")
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        transcripts = r.json().get("value", [])
        print(f"[OK] getAllTranscripts — found {len(transcripts)} transcript(s)")
        for t in transcripts:
            print(f"   - id:              {t.get('id')}")
            print(f"     meetingId:       {t.get('meetingId', 'N/A')}")
            print(f"     createdDateTime: {t.get('createdDateTime', 'N/A')}")
        return transcripts
    else:
        print(f"[ERR] getAllTranscripts {r.status_code}: {r.text[:400]}")
        return []


def get_adhoc_transcripts(token, user_id):
    """
    Fetches transcripts from ad hoc / instant calls.
    Correct endpoint (v1.0 docs): GET /adhocCalls/getAllTranscripts(userId={userId})
    Root-level OData function — userId is a REQUIRED function parameter (no quotes).
    Requires CallTranscripts.Read.All (app permission).
    """
    headers = {"Authorization": f"Bearer {token}"}

    # Correct format per official docs: root-level, userId as OData function param
    url = f"{GRAPH_API}/adhocCalls/getAllTranscripts(userId={user_id})"
    print(f"\n[A] Trying /adhocCalls/getAllTranscripts(userId={user_id[:8]}...)...")
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        transcripts = r.json().get("value", [])
        print(f"[OK] adhocCalls — found {len(transcripts)} transcript(s)")
        for t in transcripts:
            print(f"   - id:              {t.get('id')}")
            print(f"     callId:          {t.get('callId', 'N/A')}")
            print(f"     createdDateTime: {t.get('createdDateTime', 'N/A')}")
        return transcripts
    else:
        print(f"[ERR] {r.status_code}: {r.text[:400]}")

    # Also try with single-quoted userId (OData string literal style)
    url2 = f"{GRAPH_API}/adhocCalls/getAllTranscripts(userId='{user_id}')"
    print(f"\n[B] Trying with quoted userId...")
    r2 = requests.get(url2, headers=headers)
    if r2.status_code == 200:
        transcripts = r2.json().get("value", [])
        print(f"[OK] adhocCalls (quoted) — found {len(transcripts)} transcript(s)")
        for t in transcripts:
            print(f"   - id:              {t.get('id')}")
            print(f"     callId:          {t.get('callId', 'N/A')}")
            print(f"     createdDateTime: {t.get('createdDateTime', 'N/A')}")
        return transcripts
    else:
        print(f"[ERR] {r2.status_code}: {r2.text[:400]}")

    return []


def get_adhoc_transcript_content(token, user_id, call_id, transcript_id):
    """Fetch VTT content for an ad hoc call transcript."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/vtt"}
    url = f"{GRAPH_API}/users/{user_id}/adhocCalls/{call_id}/transcripts/{transcript_id}/content"
    print(f"\n[C] Fetching adhoc transcript content...")
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        preview = r.text[:500]
        print(f"[OK] Content preview:\n{'-'*40}\n{preview}\n{'-'*40}")
        return r.text
    else:
        print(f"[ERR] {r.status_code}: {r.text[:300]}")
        return None


def get_meetings(token):
    """
    Lists online meetings for the user.
    Requires CsApplicationAccessPolicy in Teams admin.
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_API}/users/{ORGANIZER_EMAIL}/onlineMeetings"
    print(f"\n[2] Trying list onlineMeetings endpoint...")
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        meetings = r.json().get("value", [])
        print(f"[OK] Meetings found: {len(meetings)}")
        for m in meetings[:5]:
            print(f"   - {m.get('subject', 'No subject')} | {m.get('startDateTime', '')} | id: {m.get('id')}")
        return meetings
    elif r.status_code == 404:
        print(f"[ERR] 404 — CsApplicationAccessPolicy may not have propagated yet (wait up to 2h)")
        print(f"      Full error: {r.text[:200]}")
        return []
    elif r.status_code == 403:
        print(f"[ERR] 403 — Missing OnlineMeetings.Read.All permission or admin consent not granted")
        return []
    else:
        print(f"[ERR] {r.status_code}: {r.text[:300]}")
        return []


def get_transcripts_for_meeting(token, meeting_id):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_API}/users/{ORGANIZER_EMAIL}/onlineMeetings/{meeting_id}/transcripts"
    print(f"\n[3] Fetching transcripts for meeting {meeting_id[:40]}...")
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        transcripts = r.json().get("value", [])
        print(f"[OK] Transcripts found: {len(transcripts)}")
        return transcripts
    else:
        print(f"[ERR] {r.status_code}: {r.text[:300]}")
        return []


def get_transcript_content(token, meeting_id, transcript_id, user_ref=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/vtt"}
    ref = user_ref or ORGANIZER_EMAIL
    url = f"{GRAPH_API}/users/{ref}/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content"
    print(f"\n[4] Fetching transcript content (user={ref[:20]}...)...")
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        preview = r.text[:500]
        print(f"[OK] Content preview:\n{'-'*40}\n{preview}\n{'-'*40}")
        return r.text
    else:
        print(f"[ERR] {r.status_code}: {r.text[:300]}")
        return None


if __name__ == "__main__":
    import time
    import sys

    RETRY = "--retry" in sys.argv
    WAIT_SECONDS = 60  # retry every 60s

    print("=== Graph API Transcript Test ===\n")

    while True:
        token = get_token()
        decode_token_roles(token)

        user_id = get_user_id(token)
        user_ref = user_id if user_id else ORGANIZER_EMAIL

        # Approach 1: getAllTranscripts
        transcripts = get_all_transcripts(token, user_ref)
        if transcripts:
            t = transcripts[0]
            meeting_id = t.get("meetingId") or t.get("id", "").split("/transcripts/")[0]
            transcript_id = t.get("id")
            if meeting_id and transcript_id:
                get_transcript_content(token, meeting_id, transcript_id, user_ref=user_id)

        # Approach 1b: adhoc calls transcripts
        adhoc_txs = []
        if user_id:
            adhoc_txs = get_adhoc_transcripts(token, user_id)
            if adhoc_txs:
                t = adhoc_txs[0]
                call_id = t.get("callId") or t.get("id", "").split("/transcripts/")[0]
                tx_id = t.get("id")
                if call_id and tx_id:
                    get_adhoc_transcript_content(token, user_id, call_id, tx_id)

        # Approach 2: list meetings
        meetings = get_meetings(token)
        if meetings:
            for m in meetings[:3]:
                txs = get_transcripts_for_meeting(token, m["id"])
                if txs:
                    get_transcript_content(token, m["id"], txs[0]["id"], user_ref=user_id)
                    break

        if transcripts or adhoc_txs or meetings:
            print("\n[DONE] Transcripts found — stopping.")
            break

        if not RETRY:
            print("\n[INFO] No transcripts yet. Run with --retry to keep polling:")
            print("       python test_graph_api.py --retry")
            break

        print(f"\n[WAIT] Nothing yet — retrying in {WAIT_SECONDS}s... (Ctrl+C to stop)\n")
        time.sleep(WAIT_SECONDS)
