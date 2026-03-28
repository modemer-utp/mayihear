"""
End-to-end pipeline test — no Teams or webhook needed.
Fetches the latest real transcript from Graph API, generates insights, posts to Monday.com.

Usage (from teams-agent/):
    pip install -r requirements.txt
    python test_pipeline.py
"""
import os
import sys
import requests

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env.dev"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

GRAPH_API = "https://graph.microsoft.com/v1.0"
ORGANIZER_EMAIL = os.environ["ORGANIZER_TEAMS_MAIL"]
TENANT_ID = os.environ["AZURE_TENANT_ID"]
CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]


def get_token() -> str:
    r = requests.post(
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default",
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_latest_transcript(token: str) -> tuple[str, str, str, str]:
    """
    Returns (organizer_email, meeting_id, transcript_id, subject) for the latest transcript.
    Tries getAllTranscripts first, falls back to listing meetings.
    """
    headers = {"Authorization": f"Bearer {token}"}

    # Resolve user GUID
    r = requests.get(f"{GRAPH_API}/users/{ORGANIZER_EMAIL}?$select=id,displayName", headers=headers)
    user_id = r.json().get("id") if r.status_code == 200 else None
    user_ref = user_id or ORGANIZER_EMAIL

    # Try getAllTranscripts
    url = f"{GRAPH_API}/users/{user_ref}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{user_ref}')"
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        items = r.json().get("value", [])
        if items:
            # Sort by createdDateTime descending to get latest
            items.sort(key=lambda x: x.get("createdDateTime", ""), reverse=True)
            latest = items[0]
            meeting_id = latest.get("meetingId") or latest.get("id", "").split("/transcripts/")[0]
            transcript_id = latest.get("id", "").split("/transcripts/")[-1]
            subject = latest.get("subject") or "Reunión Teams"
            print(f"[OK] Found transcript via getAllTranscripts — meeting: '{subject}' ({latest.get('createdDateTime', '')})")
            return ORGANIZER_EMAIL, meeting_id, transcript_id, subject

    # Fallback: list meetings and find one with a transcript
    print("[INFO] getAllTranscripts failed or empty — trying meeting list...")
    r = requests.get(f"{GRAPH_API}/users/{ORGANIZER_EMAIL}/onlineMeetings", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(f"Cannot list meetings: {r.status_code} {r.text[:300]}")

    meetings = r.json().get("value", [])
    # Sort by startDateTime descending
    meetings.sort(key=lambda m: m.get("startDateTime", ""), reverse=True)

    for meeting in meetings[:10]:
        mid = meeting["id"]
        subject = meeting.get("subject", "Reunión Teams")
        r2 = requests.get(f"{GRAPH_API}/users/{ORGANIZER_EMAIL}/onlineMeetings/{mid}/transcripts", headers=headers)
        if r2.status_code == 200:
            transcripts = r2.json().get("value", [])
            if transcripts:
                tid = transcripts[-1]["id"]  # last transcript of this meeting
                print(f"[OK] Found transcript via meeting list — '{subject}'")
                return ORGANIZER_EMAIL, mid, tid, subject

    raise RuntimeError("No transcripts found in any recent meeting. Make sure transcription was enabled.")


if __name__ == "__main__":
    import pipeline

    print("=== MayiHear Pipeline Test ===\n")

    print("[1/4] Authenticating with Graph API...")
    token = get_token()
    print("      Token OK\n")

    print("[2/4] Fetching latest transcript...")
    organizer_email, meeting_id, transcript_id, subject = fetch_latest_transcript(token)
    print(f"      organizer : {organizer_email}")
    print(f"      meeting_id: {meeting_id[:60]}...")
    print(f"      subject   : {subject}\n")

    print("[3/4] Running pipeline (transcript → Gemini → Monday.com)...")
    result = pipeline.run(organizer_email, meeting_id, transcript_id, subject)

    print(f"\n[4/4] Done!")
    print(f"      Monday item : {result['item_id']}")
    print(f"      Meeting     : {result['subject']}")
    print(f"\n--- INSIGHTS PREVIEW ---")
    print(result["insights_text"][:800] + ("..." if len(result["insights_text"]) > 800 else ""))
