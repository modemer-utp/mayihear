"""
Registers a Microsoft Graph change notification subscription so that
when a Teams meeting transcript is ready, Graph calls our webhook.

Usage:
    cd teams-agent
    python register_webhook.py

The subscription expires after 60 minutes (Graph's max for this resource).
Run this script again to renew, or deploy the auto-renew logic.
"""
import os
import sys
import json
import datetime
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env.dev"))

TENANT_ID     = os.environ["AZURE_TENANT_ID"]
CLIENT_ID     = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
ORGANIZER     = os.environ["ORGANIZER_TEAMS_MAIL"]
WEBHOOK_URL   = os.environ.get(
    "WEBHOOK_URL",
    "https://mayihear-agent.azurewebsites.net/api/webhook"
)
CLIENT_STATE  = os.environ.get("GRAPH_WEBHOOK_SECRET", "mayihear-secret")
GRAPH_API     = "https://graph.microsoft.com/v1.0"


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


def get_user_id(token: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH_API}/users/{ORGANIZER}?$select=id", headers=headers)
    r.raise_for_status()
    return r.json()["id"]


def list_subscriptions(token: str) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{GRAPH_API}/subscriptions", headers=headers)
    r.raise_for_status()
    return r.json().get("value", [])


def delete_subscription(token: str, sub_id: str):
    headers = {"Authorization": f"Bearer {token}"}
    requests.delete(f"{GRAPH_API}/subscriptions/{sub_id}", headers=headers)
    print(f"  Deleted old subscription {sub_id}")


def create_subscription(token: str, user_id: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    # Graph max expiry for transcript notifications is 60 minutes
    expiry = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=59)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    body = {
        "changeType": "created",
        "notificationUrl": WEBHOOK_URL,
        "resource": f"/users/{user_id}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{user_id}')",
        "expirationDateTime": expiry,
        "clientState": CLIENT_STATE,
    }
    r = requests.post(f"{GRAPH_API}/subscriptions", json=body, headers=headers)
    if r.status_code not in (200, 201):
        print(f"[ERR] {r.status_code}: {r.text}")
        r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    print("=== MayiHear — Graph Webhook Registration ===\n")
    print(f"Webhook URL : {WEBHOOK_URL}")
    print(f"Organizer   : {ORGANIZER}\n")

    token = get_token()
    print("[1/4] Token OK")

    user_id = get_user_id(token)
    print(f"[2/4] User ID: {user_id}")

    # Clean up existing subscriptions for the same resource
    existing = list_subscriptions(token)
    for sub in existing:
        if "getAllTranscripts" in sub.get("resource", ""):
            print(f"[3/4] Found existing subscription — deleting...")
            delete_subscription(token, sub["id"])
            break
    else:
        print("[3/4] No existing transcript subscriptions found")

    # Create new subscription
    sub = create_subscription(token, user_id)
    print(f"\n[4/4] Subscription created!")
    print(f"  id         : {sub['id']}")
    print(f"  resource   : {sub['resource']}")
    print(f"  expires    : {sub['expirationDateTime']}")
    print(f"\n✅ Graph will now call {WEBHOOK_URL} when a transcript is ready.")
    print("⚠️  Subscription expires in ~60 min. Re-run this script to renew.")
