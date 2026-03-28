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


def get_meetings(token: str, organizer_email: str) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH_API}/users/{organizer_email}/onlineMeetings", headers=headers)
    r.raise_for_status()
    return r.json().get("value", [])


def get_transcripts(token: str, organizer_email: str, meeting_id: str) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{GRAPH_API}/users/{organizer_email}/onlineMeetings/{meeting_id}/transcripts",
        headers=headers
    )
    r.raise_for_status()
    return r.json().get("value", [])


def get_transcript_content(token: str, organizer_email: str, meeting_id: str, transcript_id: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/vtt",
    }
    r = requests.get(
        f"{GRAPH_API}/users/{organizer_email}/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content",
        headers=headers
    )
    r.raise_for_status()
    return r.text
