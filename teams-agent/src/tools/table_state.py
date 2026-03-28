"""
Persistent conversation state using Azure Table Storage.
Same storage account as AzureWebJobsStorage — no extra resource needed.
Survives redeploys and multi-instance scaling.
"""
import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)
TABLE_NAME = "convstate"


def _row_key(conv_id: str) -> str:
    """MD5 hash of conv_id — Table Storage keys can't contain /, \\, #, ?"""
    return hashlib.md5(conv_id.encode()).hexdigest()


def _get_table_client():
    from azure.data.tables import TableServiceClient
    conn_str = os.environ["AzureWebJobsStorage"]
    svc = TableServiceClient.from_connection_string(conn_str)
    try:
        svc.create_table(TABLE_NAME)
    except Exception:
        pass  # Already exists
    return svc.get_table_client(TABLE_NAME)


def get_conv_state(conv_id: str) -> dict:
    """Load conversation state dict from Table Storage. Returns {} if not found."""
    try:
        client = _get_table_client()
        entity = client.get_entity(partition_key="conv", row_key=_row_key(conv_id))
        return json.loads(entity.get("state", "{}"))
    except Exception:
        return {}


def set_conv_state(conv_id: str, state: dict):
    """Persist conversation state dict to Table Storage."""
    try:
        client = _get_table_client()
        client.upsert_entity({
            "PartitionKey": "conv",
            "RowKey": _row_key(conv_id),
            "state": json.dumps(state),
        })
    except Exception as e:
        logger.warning(f"Could not save conv state for {conv_id[:20]}: {e}")
