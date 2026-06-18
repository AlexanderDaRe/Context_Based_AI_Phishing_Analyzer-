"""
OnTheHooks - Draft inject + folder move
1. POST message to drafts with historical date
2. GET the drafts folder ID
3. PATCH parentFolderId to move to inbox/sentitems
4. PATCH isDraft to false

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

def graph_post(token, path, payload):
    r = requests.post(
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload
    )
    if r.status_code in (200, 201):
        return r.json()
    log.error(f"POST {path} -> {r.status_code}: {r.text[:200]}")
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

def get_folder_id(token, upn, folder_name):
    r = requests.get(
        f"{GRAPH_BASE}/users/{upn}/mailFolders/{folder_name}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code == 200:
        return r.json().get("id")
    log.error(f"Failed to get folder {folder_name} for {upn}: {r.status_code}")
    return None

# ── Inject ────────────────────────────────────────────────────────────────────

def inject_message(token, upn, target_folder_id, msg, from_upn, to_upn):
    """Create message in drafts with historical date, then move to target folder."""

    from_addr = msg.get("from", "")
    to_addrs  = msg.get("to", [])
    date_str  = msg.get("date", "")
    headers   = msg.get("headers", {})

    payload = {
        "subject": msg.get("subject", "(no subject)"),
        "body": {
            "contentType": "Text",
            "content": msg.get("body", ""),
        },
        "from": {
            "emailAddress": {"address": from_upn, "name": from_addr}
        },
        "toRecipients": [
            {"emailAddress": {"address": to_upn, "name": to_addrs[0] if to_addrs else ""}}
        ],
        "isRead": True,
        "singleValueExtendedProperties": [],
    }

    # Set historical dates
    if date_str:
        payload["receivedDateTime"] = date_str
        payload["sentDateTime"]     = date_str

    # Threading headers
    for key, prop_id in [("In-Reply-To", "String 0x1042"), ("References", "String 0x1039"), ("Message-ID", "String 0x1035")]:
        val = headers.get(key) or headers.get(key.lower())
        if val:
            payload["singleValueExtendedProperties"].append({"id": prop_id, "value": val})

    # Step 1: create in drafts
    result = graph_post(token, f"/users/{upn}/mailFolders/drafts/messages", payload)
    if not result:
        return False
    msg_id = result.get("id")

    time.sleep(0.2)

    # Step 2: use /move action to move to target folder
    r = requests.post(
        f"{GRAPH_BASE}/users/{upn}/messages/{msg_id}/move",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"destinationId": target_folder_id}
    )
    if r.status_code not in (200, 201):
        log.error(f"Move failed for {upn}: {r.status_code}: {r.text[:200]}")
        return False

    return True

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Authenticating...")
    token = get_token()
    log.info("Token acquired.")

    # Pre-fetch folder IDs for both users
    folder_ids = {}
    for persona, upn in USER_MAP.items():
        folder_ids[upn] = {
            "inbox":     get_folder_id(token, upn, "inbox"),
            "sentitems": get_folder_id(token, upn, "sentitems"),
        }
        log.info(f"Got folder IDs for {upn}")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    threads  = data.get("threads", [])
    injected = 0
    errors   = 0

    total = sum(len(t.get("messages", [])) for t in threads)
    log.info(f"Found {total} messages. Injecting...")

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

            # Inject into recipient's inbox
            ok = inject_message(
                token, recipient_upn,
                folder_ids[recipient_upn]["inbox"],
                msg, sender_upn, recipient_upn
            )
            injected += 1 if ok else 0
            if not ok: errors += 1
            time.sleep(THROTTLE_DELAY)

            # Inject into sender's sent items
            ok = inject_message(
                token, sender_upn,
                folder_ids[sender_upn]["sentitems"],
                msg, sender_upn, recipient_upn
            )
            injected += 1 if ok else 0
            if not ok: errors += 1
            time.sleep(THROTTLE_DELAY)

    log.info(f"Done. Injected: {injected} | Errors: {errors}")

if __name__ == "__main__":
    main()
