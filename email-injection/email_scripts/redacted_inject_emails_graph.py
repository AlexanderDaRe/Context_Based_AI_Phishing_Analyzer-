"""
OnTheHooks Email Baseline - Microsoft Graph API Injector (MIME upload)
Uses raw MIME via /$value endpoint so messages appear as real emails, not drafts.

Requirements:
    pip install msal requests
"""

import json
import time
import logging
import requests
import msal
from email.mime.text import MIMEText
from email.utils import formatdate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

TENANT_ID     = "YOUR_TENANT_ID"
CLIENT_ID     = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"

USER_MAP = {
    "jordan.reyes@onthehooks.com": "testuser1@onthehooks.com",
    "ethan.brooks@onthehooks.com": "testuser2@onthehooks.com",
}

JSON_PATH      = "onthehooks_email_baseline.json"
GRAPH_BASE     = "https://graph.microsoft.com/v1.0"
SCOPE          = ["https://graph.microsoft.com/.default"]
THROTTLE_DELAY = 0.3

# ── Auth ──────────────────────────────────────────────────────────────────────

def get_token():
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"Auth failed: {result.get('error_description')}")
    return result["access_token"]

# ── MIME builder ──────────────────────────────────────────────────────────────

def build_mime(msg, from_upn, to_upn):
    """Build a raw MIME message string."""
    from_orig = msg.get("from", "")
    to_orig   = msg.get("to", [""])[0]
    headers   = msg.get("headers", {})

    mime = MIMEText(msg.get("body", ""), "plain", "utf-8")
    mime["Subject"]  = msg.get("subject", "(no subject)")
    mime["From"]     = f"{from_orig} <{from_upn}>"
    mime["To"]       = f"{to_orig} <{to_upn}>"
    mime["Date"]     = msg.get("date", formatdate())

    # Threading headers
    for key in ["Message-ID", "message-id"]:
        if headers.get(key):
            mime["Message-ID"] = headers[key]
            break
    for key in ["In-Reply-To", "in-reply-to"]:
        if headers.get(key):
            mime["In-Reply-To"] = headers[key]
            break
    for key in ["References", "references"]:
        if headers.get(key):
            mime["References"] = headers[key]
            break

    return mime.as_bytes()

# ── Graph MIME upload ─────────────────────────────────────────────────────────

def upload_mime(token, upn, folder, mime_bytes, retries=3):
    """
    Two-step MIME inject:
    1. POST to create an empty message in the folder
    2. PUT raw MIME to /{id}/$value
    """
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Step 1: create empty message slot
    create_url = f"{GRAPH_BASE}/users/{upn}/mailFolders/{folder}/messages"
    r = requests.post(create_url, headers={**auth_headers, "Content-Type": "application/json"}, json={})
    if r.status_code not in (200, 201):
        log.error(f"Failed to create message slot for {upn}: {r.status_code} {r.text[:200]}")
        return False
    msg_id = r.json().get("id")

    # Step 2: PUT raw MIME to replace the message content
    put_url = f"{GRAPH_BASE}/users/{upn}/messages/{msg_id}/$value"
    for attempt in range(retries):
        r = requests.put(put_url, headers={**auth_headers, "Content-Type": "text/plain"}, data=mime_bytes)
        if r.status_code in (200, 201, 204):
            return True
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 5))
            log.warning(f"Throttled. Waiting {wait}s...")
            time.sleep(wait)
        else:
            log.error(f"MIME PUT failed for {upn}: {r.status_code} {r.text[:200]}")
            return False
    return False

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Authenticating...")
    token = get_token()
    log.info("Token acquired.")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    threads  = data.get("threads", [])
    injected = 0
    errors   = 0

    log.info(f"Found {len(threads)} threads. Starting MIME injection...")

    for thread in threads:
        for msg in thread.get("messages", []):
            from_addr = msg.get("from", "")
            to_addrs  = msg.get("to", [])

            sender_upn    = USER_MAP.get(from_addr)
            recipient_upn = USER_MAP.get(to_addrs[0]) if to_addrs else None

            if not sender_upn or not recipient_upn:
                log.warning(f"Skipping unknown address: from={from_addr} to={to_addrs}")
                errors += 1
                continue

            mime_bytes = build_mime(msg, sender_upn, recipient_upn)

            # Sender's Sent Items
            ok = upload_mime(token, sender_upn, "sentitems", mime_bytes)
            injected += 1 if ok else 0
            if not ok: errors += 1
            time.sleep(THROTTLE_DELAY)

            # Recipient's Inbox
            ok = upload_mime(token, recipient_upn, "inbox", mime_bytes)
            injected += 1 if ok else 0
            if not ok: errors += 1
            time.sleep(THROTTLE_DELAY)

    log.info(f"Done. Injected: {injected} | Errors: {errors}")

if __name__ == "__main__":
    main()
