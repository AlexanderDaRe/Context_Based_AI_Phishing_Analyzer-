import logging
import json
import re
import requests
import azure.functions as func
from datetime import datetime, timezone, timedelta

from shared.graph_client import GraphClient
from shared.state import get_last_run, save_last_run

MONITORED_USERS = ["put user", "put user"]

ENDPOINT_URL = "put endpoint"
ENDPOINT_JWT = "put jwt"   

logger = logging.getLogger(__name__)

def main(timer: func.TimerRequest) -> None:
    """Runs on a schedule, polls both inboxes, forwards new emails."""
    if timer.past_due:
        logger.warning("Timer is past due.")

    graph = GraphClient()

    # Fetch emails received after the last successful run.
    # On the very first run, look back 2 minutes to avoid flooding with history.
    last_run = get_last_run() or (datetime.now(timezone.utc) - timedelta(minutes=2))
    run_start = datetime.now(timezone.utc)

    for user in MONITORED_USERS:
        try:
            emails = graph.get_inbox_messages_since(user, last_run)
        except Exception as exc:
            logger.error("Failed to fetch messages for %s: %s", user, exc)
            continue

        for msg in emails:
            msg_id = msg.get("id")
            try:
                payload = parse_email(msg)
                forward_to_endpoint(payload)
                logger.info("Forwarded email id=%s for user=%s", msg_id, user)
            except Exception as exc:
                logger.error("Error processing email id=%s: %s", msg_id, exc)

    save_last_run(run_start)


def parse_email(msg: dict) -> dict:
    """Extract required fields from a Microsoft Graph message object."""
    return {
        "sender":   _extract_address(msg.get("from", {})),
        "receiver": _extract_recipients(msg.get("toRecipients", [])),
        "date":     _normalise_date(msg.get("receivedDateTime", "")),
        "subject":  msg.get("subject", ""),
        "body":     _extract_body(msg.get("body", {})),
        "urls":     _extract_urls(_extract_body(msg.get("body", {}))),
        "headers":  _extract_headers(msg.get("internetMessageHeaders", [])),
    }


def _extract_address(address_obj: dict) -> str:
    return address_obj.get("emailAddress", {}).get("address", "")


def _extract_recipients(recipients: list) -> list:
    return [
        r.get("emailAddress", {}).get("address", "")
        for r in recipients
        if r.get("emailAddress", {}).get("address")
    ]


def _normalise_date(raw: str) -> str:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, AttributeError):
        return raw


def _extract_body(body_obj: dict) -> str:
    return body_obj.get("content", "")


def _extract_urls(text: str) -> list:
    return list(set(re.findall(r'https?://[^\s<>"\')\]]*', text)))


def _extract_headers(raw_headers: list) -> dict:
    return {h["name"]: h["value"] for h in raw_headers if "name" in h and "value" in h}


def forward_to_endpoint(payload: dict) -> None:
    response = requests.post(
        ENDPOINT_URL,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {ENDPOINT_JWT}",
        },
        data=json.dumps(payload, default=str),
        timeout=30,
    )
    response.raise_for_status()
