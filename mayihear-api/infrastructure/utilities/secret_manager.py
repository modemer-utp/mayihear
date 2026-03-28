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
