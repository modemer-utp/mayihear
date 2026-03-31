"""
Graph API helpers shared between bot and function_app.
Keeps credentials-based calls in one place.
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)
GRAPH_API = "https://graph.microsoft.com/v1.0"


def get_token() -> str:
    """Obtain an app-only bearer token using client credentials."""
    tenant = os.environ["AZURE_TENANT_ID"]
    r = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["AZURE_CLIENT_ID"],
            "client_secret": os.environ["AZURE_CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def resolve_email_from_aad_id(aad_object_id: str) -> str | None:
    """
    Resolve an AAD object ID → email address.
    Requires User.Read.All app permission (admin consent).
    Returns lowercase email or None on failure.
    """
    try:
        token = get_token()
        r = requests.get(
            f"{GRAPH_API}/users/{aad_object_id}?$select=mail,userPrincipalName",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            email = data.get("mail") or data.get("userPrincipalName") or ""
            return email.lower() or None
        logger.warning(f"resolve_email_from_aad_id: {r.status_code} for {aad_object_id[:8]}...")
    except Exception as e:
        logger.warning(f"resolve_email_from_aad_id failed: {e}")
    return None
