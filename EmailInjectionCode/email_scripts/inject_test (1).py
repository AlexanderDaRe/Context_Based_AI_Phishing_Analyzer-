"""
OnTheHooks - Test injector using /sendMail (today's date, real non-draft emails)

Requirements:
    pip install msal requests

-------------------------------------------------------------------------------
SETUP
-------------------------------------------------------------------------------
    python3 -m venv venv
    source venv/bin/activate
    pip install msal requests

BEFORE RUNNING
    1. Fill in TENANT_ID, CLIENT_ID, CLIENT_SECRET below
       (Entra app: phishing-lab-injector)
    2. Change JSON_PATH below to point at the baseline file, e.g.
       JSON_PATH = "onthehooks-_internal_email_baseline.json"
    3. Make sure that json file is in the same folder as this script
       (or use the full path)

RUN IT
    python3 inject_test.py

WHAT IT DOES
    Sends every message in the file's threads into testuser1/testuser2
    inboxes via Graph API. Tags each message with 5 custom headers
    (thread_id, escalation_label, spf/dkim/dmarc intended values) since
    the real Authentication-Results header can't be faked through this
    send method. Has built-in throttle/retry handling if Graph rate
    limits the run mid-way (reads Retry-After and backs off).

HEADS UP
    The baseline file has ~1000 messages total, way more than the 10
    message test set, so this will take longer to run and may hit
    throttling more. The retry logic should handle it, but keep an eye
    on the logs during the run.
-------------------------------------------------------------------------------
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

# Retry settings for throttling (HTTP 429)
MAX_RETRIES    = 5
DEFAULT_RETRY_AFTER = 5  # seconds, fallback if Graph doesn't send Retry-After


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


def send_mail(token, sender_upn, recipient_upn, msg, thread_id, escalation_label, spf, dkim, dmarc):
    """Send email from sender to recipient using /sendMail endpoint.
    Retries on HTTP 429 (throttling) using Retry-After header if present.
    """
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
            # Graph API caps custom headers at 5 per message
            "internetMessageHeaders": [
                {"name": "X-Test-Thread-Id", "value": str(thread_id)},
                {"name": "X-Test-Escalation-Label", "value": str(escalation_label)},
                {"name": "X-Test-SPF-Intended", "value": str(spf)},
                {"name": "X-Test-DKIM-Intended", "value": str(dkim)},
                {"name": "X-Test-DMARC-Intended", "value": str(dmarc)}
            ]
        },
        "saveToSentItems": "true"
    }

    for attempt in range(1, MAX_RETRIES + 1):
        r = requests.post(url, headers=headers, json=payload)

        if r.status_code == 202:
            return True

        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", DEFAULT_RETRY_AFTER))
            log.warning(
                f"Throttled (429) sending for {sender_upn}, attempt {attempt}/{MAX_RETRIES}, "
                f"waiting {retry_after}s before retry"
            )
            time.sleep(retry_after)
            continue

        # Any other error, don't retry, just log and bail
        log.error(f"sendMail failed for {sender_upn}: {r.status_code} {r.text[:200]}")
        return False

    log.error(f"sendMail permanently failed for {sender_upn} after {MAX_RETRIES} retries (throttled)")
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

    total_messages = sum(len(t.get("messages", [])) for t in threads)
    log.info(f"Found {total_messages} messages across {len(threads)} threads. Sending...")

    for thread in threads:
        thread_id        = thread.get("thread_id", "")
        escalation_label = thread.get("escalation_label", "")

        for msg in thread.get("messages", []):
            from_addr = msg.get("from", "")
            to_addrs  = msg.get("to", [])

            sender_upn    = USER_MAP.get(from_addr)
            recipient_upn = USER_MAP.get(to_addrs[0]) if to_addrs else None

            if not sender_upn or not recipient_upn:
                log.warning(f"Skipping unknown address: from={from_addr} to={to_addrs}")
                errors += 1
                continue

            msg_headers = msg.get("headers", {})
            spf   = msg_headers.get("SPF", "")
            dkim  = msg_headers.get("DKIM", "")
            dmarc = msg_headers.get("DMARC", "")

            ok = send_mail(
                token, sender_upn, recipient_upn, msg,
                thread_id, escalation_label, spf, dkim, dmarc
            )
            if ok:
                sent += 1
                log.info(f"Sent: {msg.get('subject','(no subject)')} | {sender_upn} -> {recipient_upn}")
            else:
                errors += 1

            time.sleep(THROTTLE_DELAY)

    log.info(f"Done. Sent: {sent} | Errors: {errors}")


if __name__ == "__main__":
    main()
