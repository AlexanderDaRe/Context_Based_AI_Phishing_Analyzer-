import json
import logging
import os
from datetime import datetime, timezone

from azure.storage.blob import BlobServiceClient, BlobClient

logger = logging.getLogger(__name__)

CONTAINER = "email-parser-state"
BLOB_NAME  = "last_run.json"


def _blob_client() -> BlobClient:
    svc = BlobServiceClient.from_connection_string(os.environ["AzureWebJobsStorage"])
    try:
        svc.create_container(CONTAINER)
    except Exception:
        pass
    return svc.get_blob_client(container=CONTAINER, blob=BLOB_NAME)


def get_last_run() -> datetime | None:
    try:
        data = json.loads(_blob_client().download_blob().readall())
        return datetime.fromisoformat(data["last_run"])
    except Exception:
        return None


def save_last_run(dt: datetime) -> None:
    _blob_client().upload_blob(
        json.dumps({"last_run": dt.isoformat()}),
        overwrite=True,
    )
