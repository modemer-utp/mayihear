import os
from dotenv import load_dotenv

load_dotenv()


def get_openai_api_key() -> str:
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    return key


def get_gemini_api_key() -> str:
    key = os.getenv('GEMINI_API_KEY')
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    return key


def get_anthropic_api_key() -> str:
    key = os.getenv('ANTHROPIC_API_KEY')
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    return key


def get_monday_api_token() -> str:
    key = os.getenv('MONDAY_API_TOKEN')
    if not key:
        raise RuntimeError("MONDAY_API_TOKEN not set in .env")
    return key


def get_monday_board_id() -> str:
    val = os.getenv('MONDAY_BOARD_ID')
    if not val:
        raise RuntimeError("MONDAY_BOARD_ID not set in .env")
    return val


def get_monday_column_id() -> str:
    val = os.getenv('MONDAY_COLUMN_ID')
    if not val:
        raise RuntimeError("MONDAY_COLUMN_ID not set in .env")
    return val
