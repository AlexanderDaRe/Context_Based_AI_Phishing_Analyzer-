"""
shared/pending_remediation.py

Tracks phishing messages that were detected and contained (Junk-moved) but whose
Defender moveToQuarantine could not complete yet — almost always because Defender
had not finished ingesting the message into MailMetadata at the instant of
detection (ingestion lag surfaces as a 418 "Could not find MailMetadata").

Each entry is retried on subsequent timer runs until the Defender quarantine
succeeds or the entry ages out (MAX_AGE_MINUTES). Stored as a single JSON blob in
the same container used for run state.
"""

import os
import json
import logging

from azure.storage.blob import BlobServiceClient, BlobClient

logger = logging.getLogger(__name__)

CONTAINER = "email-parser-state"
BLOB_NAME = "pending_remediations.json"

# Stop retrying an entry after this many minutes. Defender ingestion is normally
# well within this window; beyond it, treat as a permanent failure and drop
# (the message is still contained in Junk).
MAX_AGE_MINUTES = 60


def _blob_client() -> BlobClient:
    svc = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])
    try:
        svc.create_container(CONTAINER)
    except Exception:
        pass
    return svc.get_blob_client(container=CONTAINER, blob=BLOB_NAME)


def load_pending() -> list:
    try:
        return json.loads(_blob_client().download_blob().readall())
    except Exception:
        return []


def save_pending(items: list) -> None:
    _blob_client().upload_blob(json.dumps(items), overwrite=True)


def add_pending(items: list, network_message_id: str, recipient: str,
                subject: str = "") -> list:
    """Append a message to the pending list, deduped on (nmid, recipient)."""
    from datetime import datetime, timezone
    key = (network_message_id, recipient)
    for i in items:
        if (i.get("nmid"), i.get("recipient")) == key:
            return items
    items.append({
        "nmid":       network_message_id,
        "recipient":  recipient,
        "subject":    subject,
        "first_seen": datetime.now(timezone.utc).isoformat(),
    })
    return items
