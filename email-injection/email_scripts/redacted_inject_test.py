"""
OnTheHooks - Test injector using /sendMail (today's date, real non-draft emails)

Requirements:
    pip install msal requests
"""

import json
import time
import logging
import requests
import msal

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
THROTTLE_DELAY = 0.5

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

def send_mail(token, sender_upn, recipient_upn, msg):
    """Send email from sender to recipient using /sendMail endpoint."""
    url = f"{GRAPH_BASE}/users/{sender_upn}/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
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
    r = requests.post(url, headers=headers, json=payload)
    if r.status_code == 202:
        return True
    else:
        log.error(f"sendMail failed for {sender_upn}: {r.status_code} {r.text[:200]}")
        return False

def main():
    log.info("Authenticating...")
    token = get_token()
    log.info("Token acquired.")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    threads  = data.get("threads", [])
    sent     = 0
    errors   = 0

    log.info(f"Found {sum(len(t.get('messages',[])) for t in threads)} messages. Sending...")

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

            ok = send_mail(token, sender_upn, recipient_upn, msg)
            if ok:
                sent += 1
                log.info(f"Sent: {msg.get('subject','(no subject)')} | {sender_upn} -> {recipient_upn}")
            else:
                errors += 1

            time.sleep(THROTTLE_DELAY)

    log.info(f"Done. Sent: {sent} | Errors: {errors}")

if __name__ == "__main__":
    main()
