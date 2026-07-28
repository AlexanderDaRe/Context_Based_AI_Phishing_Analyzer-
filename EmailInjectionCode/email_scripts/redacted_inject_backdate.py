"""
OnTheHooks - sendMail + backdate injector
1. Sends email via /sendMail (real non-draft)
2. Finds the message in recipient inbox and sender sent items
3. PATCHes receivedDateTime and sentDateTime to original JSON date

Requirements:
    pip install msal requests
"""

import json
import time
import logging
import requests
import msal
from urllib.parse import urlencode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TENANT_ID     = "YOUR_TENANT_ID"
CLIENT_ID     = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"

USER_MAP = {
    "jordan.reyes@onthehooks.com": "testuser1@onthehooks.com",
    "ethan.brooks@onthehooks.com": "testuser2@onthehooks.com",
}

JSON_PATH      = "onthehooks_test_10.json"
GRAPH_BASE     = "https://graph.microsoft.com/v1.0"
SCOPE          = ["https://graph.microsoft.com/.default"]
SEND_DELAY     = 5.0   # wait after send before querying
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

# ── Graph helpers ─────────────────────────────────────────────────────────────

def graph_get(token, path):
    r = requests.get(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code == 200:
        return r.json()
    log.error(f"GET {path} -> {r.status_code}: {r.text[:200]}")
    return None

def graph_patch(token, path, payload):
    r = requests.patch(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload
    )
    if r.status_code in (200, 201, 204):
        return True
    log.error(f"PATCH {path} -> {r.status_code}: {r.text[:200]}")
    return False

# ── Send ──────────────────────────────────────────────────────────────────────

def send_mail(token, sender_upn, recipient_upn, msg):
    url = f"{GRAPH_BASE}/users/{sender_upn}/sendMail"
    payload = {
        "message": {
            "subject": msg.get("subject", "(no subject)"),
            "body": {
                "contentType": "Text",
                "content": msg.get("body", ""),
            },
            "toRecipients": [
                {"emailAddress": {"address": recipient_upn}}
            ],
        },
        "saveToSentItems": "true"
    }
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload
    )
    if r.status_code == 202:
        return True
    log.error(f"sendMail failed for {sender_upn}: {r.status_code} {r.text[:200]}")
    return False

# ── Find message by subject ───────────────────────────────────────────────────

def find_message(token, upn, folder, subject, retries=3):
    """Query a folder for the most recent message matching the subject."""
    query = urlencode({"$filter": f"subject eq '{subject}'", "$top": "1"})
    path = f"/users/{upn}/mailFolders/{folder}/messages?{query}"
    for attempt in range(retries):
        result = graph_get(token, path)
        if result and result.get("value"):
            return result["value"][0]["id"]
        log.warning(f"Message not found yet for {upn} (attempt {attempt + 1}), retrying...")
        time.sleep(1.5)
    return None

# ── Backdate ──────────────────────────────────────────────────────────────────

def backdate_message(token, upn, msg_id, date_str):
    """PATCH sentDateTime and receivedDateTime to the original JSON date."""
    return graph_patch(token, f"/users/{upn}/messages/{msg_id}", {
        "receivedDateTime": date_str,
        "sentDateTime": date_str,
    })

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Authenticating...")
    token = get_token()
    log.info("Token acquired.")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    threads  = data.get("threads", [])
    sent     = 0
    backdated = 0
    errors   = 0

    total = sum(len(t.get("messages", [])) for t in threads)
    log.info(f"Found {total} messages. Sending + backdating...")

    for thread in threads:
        for msg in thread.get("messages", []):
            from_addr = msg.get("from", "")
            to_addrs  = msg.get("to", [])
            subject   = msg.get("subject", "(no subject)")
            date_str  = msg.get("date", "")

            sender_upn    = USER_MAP.get(from_addr)
            recipient_upn = USER_MAP.get(to_addrs[0]) if to_addrs else None

            if not sender_upn or not recipient_upn:
                log.warning(f"Skipping unknown address: from={from_addr} to={to_addrs}")
                errors += 1
                continue

            # Step 1: send
            ok = send_mail(token, sender_upn, recipient_upn, msg)
            if not ok:
                errors += 1
                continue
            sent += 1
            log.info(f"Sent: {subject[:50]} | {sender_upn} -> {recipient_upn}")

            # Step 2: wait for Graph to index it
            time.sleep(SEND_DELAY)

            # Step 3: find and backdate recipient's inbox copy
            msg_id = find_message(token, recipient_upn, "inbox", subject)
            if msg_id and date_str:
                ok = backdate_message(token, recipient_upn, msg_id, date_str)
                if ok:
                    backdated += 1
                    log.info(f"Backdated inbox copy to {date_str}")
            else:
                log.warning(f"Could not find inbox copy for backdating: {subject[:50]}")

            time.sleep(THROTTLE_DELAY)

            # Step 4: find and backdate sender's sent items copy
            msg_id = find_message(token, sender_upn, "sentitems", subject)
            if msg_id and date_str:
                ok = backdate_message(token, sender_upn, msg_id, date_str)
                if ok:
                    backdated += 1
                    log.info(f"Backdated sentitems copy to {date_str}")
            else:
                log.warning(f"Could not find sentitems copy for backdating: {subject[:50]}")

            time.sleep(THROTTLE_DELAY)

    log.info(f"Done. Sent: {sent} | Backdated: {backdated} | Errors: {errors}")

if __name__ == "__main__":
    main()
