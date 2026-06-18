# Email Injection - Mailbox Population Scripts

This folder contains scripts used to populate the OnTheHooks M365 test environment with a synthetic email dataset for phishing detection baseline testing.

---

## Overview

The goal was to inject a synthetic dataset of ~1,000 emails exchanged between two fictional OnTheHooks employees (Jordan Reyes and Ethan Brooks) into two M365 test mailboxes (testuser1 and testuser2) via the Microsoft Graph API. The injected emails populate the Inbox and Sent Items of both accounts to simulate a realistic internal email history.

The actual behavioral baseline used by the detection model lives in the OpenWebUI knowledge base (ChromaDB + nomic-embed-text), where original email dates and metadata are fully preserved.

---

## Prerequisites

- Python 3.x
- Microsoft 365 Business Premium tenant
- Entra ID app registration with the following Graph API **Application** permissions (admin consent granted):
  - `Mail.ReadWrite`
  - `Mail.Send`
- App credentials: Tenant ID, Client ID, Client Secret

```bash
pip install msal requests
```

---

## Scripts

### `slice_emails.py`
Slices the first 10 messages out of the full baseline JSON into a smaller test file (`onthehooks_test_10.json`). Used for testing injection approaches before running against the full dataset.

```bash
python3 slice_emails.py
```

---

### `inject_emails_graph.py`
First injection attempt. POSTs messages directly to inbox/sentitems folders via Graph API using a JSON payload with MAPI extended properties for threading headers. Messages injected correctly but were flagged as drafts by Outlook regardless of `isDraft: false` in the payload. Multiple workarounds attempted (PATCH after POST, raw MIME upload via `$value` endpoint) -- all accepted by Graph but draft flag persisted.

```bash
python3 inject_emails_graph.py
```

---

### `inject_move.py`
Second approach. Creates messages in the Drafts folder first (which preserves historical dates from the JSON), then moves them to inbox/sentitems using the Graph `/move` action. Move worked correctly but Outlook continued to display the draft label since the message was never sent through the mail system. Graph API does not allow clearing the draft flag on messages that were never actually sent.

```bash
python3 inject_move.py
```

---

### `inject_test.py`
Working solution. Uses the `/sendMail` endpoint to send emails directly from the sender account to the recipient account. Messages land in the recipient's Inbox and sender's Sent Items as real non-draft emails. Requires `Mail.Send` application permission in addition to `Mail.ReadWrite`.

Limitation: Graph API does not allow backdating sent messages so all injected emails carry the injection date rather than the original dates from the JSON dataset. This does not affect the detection model since the knowledge base preserves original metadata.

```bash
python3 inject_test.py
```

---

### `inject_backdate.py`
Extended version of `inject_test.py` that attempts to backdate messages after sending by querying the injected message by subject and PATCHing `receivedDateTime` and `sentDateTime`. Graph API accepts the PATCH and returns 200 but silently ignores the date change on sent messages. Approach was abandoned in favour of accepting injection-date timestamps.

```bash
python3 inject_backdate.py
```

---

## Dataset

- **File:** `onthehooks_email_baseline.json`
- **Size:** ~2.35MB
- **Contents:** ~1,000 emails across 321 threads between jordan.reyes@onthehooks.com and ethan.brooks@onthehooks.com
- **Format:** JSON with RFC 5322 headers (Message-ID, In-Reply-To, References), from, to, date, subject, body per message

---

## User Mapping

| Fictional Persona | M365 Test Account |
|---|---|
| jordan.reyes@onthehooks.com | testuser1@onthehooks.com |
| ethan.brooks@onthehooks.com | testuser2@onthehooks.com |

---

## Notes

- All scripts use MSAL client credentials flow for authentication
- Throttle delays are included to avoid Graph API rate limiting (429 responses)
- Final working script is `inject_test.py` -- swap `JSON_PATH` to `onthehooks_email_baseline.json` to run against the full dataset
