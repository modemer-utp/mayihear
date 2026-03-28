"""
Persistent storage for conversation references using Azure Blob Storage.
Survives redeploys — uses the same storage account as AzureWebJobsStorage.
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

CONTAINER = "mayihear-state"
CONV_REF_BLOB = "conversation_ref.json"
PROCESSED_IDS_BLOB = "processed_transcripts.json"


def _get_container_client():
    from azure.storage.blob import BlobServiceClient
    conn_str = os.environ["AzureWebJobsStorage"]
    client = BlobServiceClient.from_connection_string(conn_str)
    container = client.get_container_client(CONTAINER)
    try:
        container.create_container()
    except Exception:
        pass  # Already exists
    return container


def save_conversation_ref(ref_dict: dict):
    """Persist conversation reference dict to blob storage."""
    try:
        container = _get_container_client()
        container.upload_blob(CONV_REF_BLOB, json.dumps(ref_dict), overwrite=True)
        logger.info("Conversation reference saved to blob storage")
    except Exception as e:
        logger.warning(f"Could not save conversation ref: {e}")


def load_processed_ids() -> set:
    """Load set of already-processed transcript IDs from blob storage."""
    try:
        from azure.storage.blob import BlobServiceClient
        conn_str = os.environ["AzureWebJobsStorage"]
        client = BlobServiceClient.from_connection_string(conn_str)
        blob = client.get_blob_client(container=CONTAINER, blob=PROCESSED_IDS_BLOB)
        data = blob.download_blob().readall()
        return set(json.loads(data))
    except Exception:
        return set()


def save_processed_ids(ids: set):
    """Persist set of processed transcript IDs to blob storage."""
    try:
        container = _get_container_client()
        container.upload_blob(PROCESSED_IDS_BLOB, json.dumps(list(ids)), overwrite=True)
    except Exception as e:
        logger.warning(f"Could not save processed IDs: {e}")


def load_conversation_ref() -> dict | None:
    """Load conversation reference dict from blob storage. Returns None if not found."""
    try:
        from azure.storage.blob import BlobServiceClient
        conn_str = os.environ["AzureWebJobsStorage"]
        client = BlobServiceClient.from_connection_string(conn_str)
        blob = client.get_blob_client(container=CONTAINER, blob=CONV_REF_BLOB)
        data = blob.download_blob().readall()
        logger.info("Conversation reference loaded from blob storage")
        return json.loads(data)
    except Exception:
        return None
