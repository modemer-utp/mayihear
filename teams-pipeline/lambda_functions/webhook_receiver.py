"""
Lambda: webhook_receiver
Receives Microsoft Graph change notifications for Teams transcripts.
Validates the request, then enqueues to SQS for async processing.
"""
import hashlib
import hmac
import json
import os

import boto3

SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
GRAPH_WEBHOOK_SECRET = os.environ.get("GRAPH_WEBHOOK_SECRET", "")

sqs = boto3.client("sqs")


def handler(event, context):
    params = event.get("queryStringParameters") or {}

    # Graph API sends a validation token on subscription creation — must echo it back
    if "validationToken" in params:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/plain"},
            "body": params["validationToken"],
        }

    body = json.loads(event.get("body") or "{}")
    notifications = body.get("value", [])

    for notification in notifications:
        resource = notification.get("resource", "")
        # Only process transcript notifications
        if "transcripts" not in resource:
            continue

        # Parse: /users/{email}/onlineMeetings/{meetingId}/transcripts/{transcriptId}
        parts = resource.strip("/").split("/")
        # parts: ['users', email, 'onlineMeetings', meetingId, 'transcripts', transcriptId]
        if len(parts) < 6:
            continue

        message = {
            "organizer_email": parts[1],
            "meeting_id": parts[3],
            "transcript_id": parts[5],
            "subject": notification.get("resourceData", {}).get("subject", "Reunion Teams"),
        }

        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message),
        )
        print(f"[OK] Enqueued transcript: {message['meeting_id']}")

    return {"statusCode": 202, "body": "Accepted"}
