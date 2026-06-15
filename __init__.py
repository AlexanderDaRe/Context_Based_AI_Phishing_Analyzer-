import logging
import json
import re
import requests
import azure.functions as func
from datetime import datetime, timezone, timedelta
from azure.communication.email import EmailClient

from shared.graph_client import GraphClient
from shared.state import get_last_run, save_last_run
from shared.send_email import sendEmail

MONITORED_USERS = ["TestUser1@onthehooks.com", "TestUser2@onthehooks.com"]

ENDPOINT_URL = "https://openui.evil-friends.com/api/chat/completions"
ENDPOINT_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImY4YTY3YjQ4LTg5OWUtNDY0ZS04MzllLWNkZmJhZjdhNGYzZCIsImV4cCI6MTc4MDYyODI5MSwianRpIjoiOTJkYmFhOTQtMTgxNi00YmEzLThmZGQtNDFiMjA5OGZhMGVkIiwiaWF0IjoxNzc4MjA5MDkxfQ.dpDjhONOu2EERfa3wu83EYyp9IYEZYwvBtjmAMOxNZs"   
MODEL_ID = "gemma4:e4b"


logger = logging.getLogger(__name__)


def main(timer: func.TimerRequest) -> None:
    """Runs on a schedule, polls both inboxes, forwards new emails."""
    if timer.past_due:
        logger.warning("Timer is past due.")
 
    graph = GraphClient()
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
                email_json = parse_email(msg)
                response = forward_to_endpoint(email_json)
                logger.info("Forwarded email id=%s, response=%s", msg_id, response)

                responseParsed = json.loads(response)
                if responseParsed["True/false"] == "True":
                    sendEmail( user , msg["subject"], responseParsed["Justification"] )

            except Exception as exc:
                logger.error("Error processing email id=%s: %s", msg_id, exc)
 
    save_last_run(run_start)
 
 
# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
 
def parse_email(msg: dict) -> dict:
    """Extract required fields from a Microsoft Graph message object."""
    body = _extract_body(msg.get("body", {}))
    return {
        "sender":   _extract_address(msg.get("from", {})),
        "receiver": _extract_recipients(msg.get("toRecipients", [])),
        "date":     _normalise_date(msg.get("receivedDateTime", "")),
        "subject":  msg.get("subject", ""),
        "body":     body,
        "urls":     _extract_urls(body),
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
 
 
# ---------------------------------------------------------------------------
# Forwarding
# ---------------------------------------------------------------------------
 
def forward_to_endpoint(email_json: dict) -> dict:
    """Wrap the email JSON into the chat completions payload and POST it."""
    payload = {
        "model": MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": json.dumps(email_json, default=str)
            }
        ],
        "stream": False,
        "chat_id": "",
        "parent_id": ""
    }
 
    response = requests.post(
        ENDPOINT_URL,
        headers={
            "Authorization": f"Bearer {ENDPOINT_JWT}",
            "Content-Type":  "application/json",
        },
        json=payload,
        timeout=60.0,
    )
 
    if response.status_code == 200:
        return response.json()
    else:
        raise RuntimeError(f"{response.status_code}: {response.text}")
 



