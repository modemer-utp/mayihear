import os
from dotenv import load_dotenv

load_dotenv()

# Runtime overrides — set by settings panel without restart
_overrides: dict = {}


def set_override(key: str, value: str):
    _overrides[key] = value


def _get(key: str, error_msg: str) -> str:
    if key in _overrides and _overrides[key]:
        return _overrides[key]
    val = os.getenv(key)
    if not val:
        raise RuntimeError(error_msg)
    return val


def _get_optional(key: str) -> str:
    if key in _overrides and _overrides[key]:
        return _overrides[key]
    return os.getenv(key, '')


def get_openai_api_key() -> str:
    return _get('OPENAI_API_KEY', "OPENAI_API_KEY not set")


def get_gemini_api_key() -> str:
    return _get('GEMINI_API_KEY', "GEMINI_API_KEY not set — configure it in Settings (⚙)")


def get_anthropic_api_key() -> str:
    return _get('ANTHROPIC_API_KEY', "ANTHROPIC_API_KEY not set")


def get_monday_api_token() -> str:
    return _get('MONDAY_API_TOKEN', "MONDAY_API_TOKEN not set — configure it in Settings (⚙)")


def get_monday_board_id() -> str:
    return _get('MONDAY_BOARD_ID', "MONDAY_BOARD_ID not set — configure it in Settings (⚙)")


def get_monday_column_id() -> str:
    return _get('MONDAY_COLUMN_ID', "MONDAY_COLUMN_ID not set — configure it in Settings (⚙)")


def get_vertex_sa_path() -> str:
    """Returns the service account JSON path if configured, empty string otherwise."""
    return _get_optional('VERTEX_SA_PATH')


def get_vertex_credentials():
    """
    Returns (credentials, project_id) if a Vertex AI service account is configured,
    or (None, None) to fall back to AI Studio key.
    """
    path = get_vertex_sa_path()
    if not path or not os.path.isfile(path):
        return None, None
    try:
        import json
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(path) as f:
            sa_data = json.load(f)
        project_id = sa_data.get('project_id', '')
        creds = service_account.Credentials.from_service_account_file(
            path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(Request())
        return creds, project_id
    except Exception as e:
        raise RuntimeError(f"Vertex AI credentials error: {e}")
