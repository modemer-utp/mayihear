"""
Core processing pipeline: meeting metadata → transcript → insights → Monday.com
Called by both the Teams bot activity handler and the Graph API webhook receiver.
"""
import os
import logging

from tools.graph_client import get_token, get_transcript_content
from tools.vtt_parser import parse_vtt
from tools.llm import generate_insights, generate_insights_custom, format_insights_for_monday
from tools.monday import create_meeting_item, setup_board, post_meeting_update

logger = logging.getLogger(__name__)

BOARD_ID = os.environ["MONDAY_BOARD_ID"]

# Column ID cache per board_id
_col_id_cache: dict = {}


def get_insights_column_id(board_id: str | None = None) -> str:
    bid = board_id or BOARD_ID
    if bid not in _col_id_cache:
        _col_id_cache[bid] = setup_board(bid)
    return _col_id_cache[bid]


def fetch_transcript(organizer_email: str, meeting_id: str, transcript_id: str, subject: str) -> dict:
    """
    Step 1+2: fetch and parse transcript only.
    Returns dict with subject and transcript_text.
    """
    logger.info(f"Fetching transcript — meeting='{subject}'")
    token = get_token()
    vtt = get_transcript_content(token, organizer_email, meeting_id, transcript_id)
    logger.info(f"Fetched transcript ({len(vtt)} chars)")
    transcript_text = parse_vtt(vtt)
    logger.info(f"Parsed transcript ({len(transcript_text)} chars)")
    return {"subject": subject, "transcript_text": transcript_text}


def generate(transcript_text: str, subject: str, custom_prompt: str | None = None) -> dict:
    """
    Step 3: generate insights from transcript text.
    If custom_prompt is set, uses it directly (free-form output).
    Otherwise uses the default structured JSON prompt.
    Returns dict with insights and insights_text.
    """
    if custom_prompt:
        insights_text = generate_insights_custom(transcript_text, custom_prompt)
        insights = {}
        logger.info("Insights generated (custom prompt)")
    else:
        insights = generate_insights(transcript_text)
        insights_text = format_insights_for_monday(insights)
        logger.info("Insights generated (default prompt)")
    return {"subject": subject, "transcript_text": transcript_text, "insights": insights, "insights_text": insights_text}


def post_to_monday(subject: str, insights_text: str, board_id: str | None = None) -> str:
    """
    Post insights to Monday's Actualizaciones item as an Update.
    Newest meeting appears first in Monday's Updates feed.
    Returns the update_id.
    """
    bid = board_id or BOARD_ID
    update_id = post_meeting_update(bid, subject, insights_text)
    logger.info(f"Posted meeting update to Monday — update_id={update_id}")
    return update_id


def run(organizer_email: str, meeting_id: str, transcript_id: str, subject: str, board_id: str | None = None) -> dict:
    """Full pipeline: transcript → insights → Monday. Returns summary dict."""
    data = fetch_transcript(organizer_email, meeting_id, transcript_id, subject)
    result = generate(data["transcript_text"], subject)
    item_id = post_to_monday(subject, result["insights_text"], board_id)
    return {**result, "item_id": item_id}
