import logging
import json
import re
import html
import requests
import azure.functions as func
from datetime import datetime, timezone, timedelta
from azure.communication.email import EmailClient
import os

from shared.graph_client import GraphClient
from shared.state import get_last_run, save_last_run
from shared.send_email import sendEmail, sendIncidentReportEmail
from shared.incident_response import run_incident_response, save_incident_report
from shared.pending_remediation import (
    load_pending, save_pending, add_pending, MAX_AGE_MINUTES,
)

MONITORED_USERS = ["TestUser1@onthehooks.com", "TestUser2@onthehooks.com"]

# Sender to ignore (our own ACS no-reply address).
IGNORED_SENDER = "donotreply@8c08f65d-8af3-464f-9dd4-6fc0cbe11065.us4.azurecomm.net"

ENDPOINT_URL = "https://openui.evil-friends.com/api/chat/completions"
ENDPOINT_JWT = os.environ["ENDPOINT_JWT"]   
MODEL_ID = "dorado"

# Max characters of (plain-text) body kept per email before truncating.
MAX_BODY_CHARS = 2000

# Only these headers are forwarded to the model; everything else (antispam
# blobs, routing/diagnostic X-MS-Exchange-* fields) is dropped to keep the
# prompt small. Names are compared lower-cased.
_USEFUL_HEADERS = {
    "from",
    "reply-to",
    "return-path",
    "to",
    "authentication-results",
    "received-spf",
    "x-ms-exchange-organization-authas",              # Internal vs External
    "x-ms-exchange-organization-messagedirectionality",  # Originating/Incoming
    "x-ms-exchange-organization-network-message-id",  # Defender NetworkMessageId
}


logger = logging.getLogger(__name__)


def main(timer: func.TimerRequest) -> None:
    """Runs on a schedule, polls both inboxes, forwards new emails."""
    if timer.past_due:
        logger.warning("Timer is past due.")
 
    graph = GraphClient()

    # Retry Defender quarantine for messages that Defender had not yet ingested
    # when they were first detected (the common cause of the remediate 418).
    retry_pending_remediations(graph)

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

                if email_json["sender"].lower() == IGNORED_SENDER.lower():
                    logger.info("Ignoring email id=%s from %s", msg_id, IGNORED_SENDER)
                    continue

                response = forward_to_endpoint(email_json)
                logger.info(
                    "Forwarded email id=%s, response=%s", msg_id, response,
                )

                verdict = parse_verdict(response)
                if verdict["is_threat"]:
                    # Defender keys both remediation and hunting off the
                    # NetworkMessageId (a GUID) — not the Graph mail id — which
                    # is carried in the message headers. Extract it once.
                    network_message_id = _header_ci(
                        email_json["headers"],
                        "X-MS-Exchange-Organization-Network-Message-Id",
                    )

                    # 1) contain FIRST — prefer Defender soft-delete (recoverable
                    # via the Action center). Fall back to a Junk-folder move only
                    # if Defender remediation is unavailable (no NetworkMessageId,
                    # missing permission, or no Defender for O365). Non-fatal so a
                    # failed alert/IR later can't undo containment.
                    try:
                        if not network_message_id:
                            raise RuntimeError("no NetworkMessageId header")
                        graph.remediate_email(
                            network_message_id, user, action="softDelete",
                        )
                        logger.info(
                            "Defender soft-deleted phishing email id=%s (nmid=%s) "
                            "user=%s (confidence=%s)",
                            msg_id, network_message_id, user, verdict["confidence"],
                        )
                    except Exception as exc:
                        logger.warning(
                            "Defender remediation unavailable for id=%s (%s); "
                            "falling back to Junk move.", msg_id, exc,
                        )
                        try:
                            graph.quarantine_message(user, msg_id)
                            logger.info(
                                "Quarantined (Junk) phishing email id=%s user=%s "
                                "(confidence=%s)", msg_id, user, verdict["confidence"],
                            )
                        except Exception as exc2:
                            logger.error(
                                "Containment failed entirely for id=%s: %s",
                                msg_id, exc2,
                            )
                        # Queue for deferred Defender quarantine. Most 418s here
                        # are just Defender not having ingested the message yet;
                        # a later run retries once MailMetadata exists.
                        if network_message_id:
                            try:
                                save_pending(add_pending(
                                    load_pending(), network_message_id, user,
                                    msg.get("subject", ""),
                                ))
                            except Exception as exc3:
                                logger.error(
                                    "Could not queue pending remediation for "
                                    "id=%s: %s", msg_id, exc3,
                                )
                    # 2) alert the user. Non-fatal: a throttled (ACS 429) or
                    # failed alert is logged but must not abort processing.
                    try:
                        sendEmail(
                            user,
                            msg["subject"],
                            verdict["justification"],
                            verdict["confidence"],
                        )
                    except Exception as exc:
                        logger.error(
                            "Alert email failed for id=%s (already contained): %s",
                            msg_id, exc,
                        )
                    # 3) kick off early-stage incident response (reuses the
                    # NetworkMessageId extracted above).
                    if network_message_id:
                        try:
                            report = run_incident_response(network_message_id, graph)
                            logger.info(
                                "Incident response for id=%s (nmid=%s): %s",
                                msg_id, network_message_id,
                                json.dumps(report, default=str),
                            )
                            save_incident_report(network_message_id, report)
                            try:
                                sendIncidentReportEmail(msg["subject"], report)
                            except Exception as exc:
                                logger.error(
                                    "Admin incident report email failed for "
                                    "id=%s: %s", msg_id, exc,
                                )
                        except Exception as exc:
                            logger.error(
                                "Incident response failed for id=%s: %s",
                                msg_id, exc,
                            )
                    else:
                        logger.warning(
                            "No NetworkMessageId header on id=%s; "
                            "skipping incident response.", msg_id,
                        )

            except Exception as exc:
                logger.error("Error processing email id=%s: %s", msg_id, exc)
 
    save_last_run(run_start)
 
 
def retry_pending_remediations(graph) -> None:
    """Retry Defender softDelete for messages contained via Junk move but
    not yet ingested by Defender when first detected (the common cause of the
    remediate 418). Runs each timer tick; drops entries older than
    MAX_AGE_MINUTES. On success, regenerates the (previously empty) incident
    report now that Defender has data for the message.
    """
    try:
        items = load_pending()
    except Exception as exc:
        logger.error("Could not load pending remediations: %s", exc)
        return
    if not items:
        return

    now = datetime.now(timezone.utc)
    still_pending = []
    for item in items:
        nmid = item.get("nmid")
        recipient = item.get("recipient")
        subject = item.get("subject", "")
        try:
            first_seen = datetime.fromisoformat(item["first_seen"])
        except Exception:
            first_seen = now
        try:
            graph.remediate_email(nmid, recipient, action="softDelete")
            logger.info(
                "Deferred Defender soft-delete succeeded nmid=%s user=%s",
                nmid, recipient,
            )
            try:
                report = run_incident_response(nmid, graph)
                save_incident_report(nmid, report)
            except Exception as exc:
                logger.error(
                    "Deferred incident response failed nmid=%s: %s", nmid, exc,
                )
        except Exception as exc:
            age_min = (now - first_seen).total_seconds() / 60.0
            if age_min >= MAX_AGE_MINUTES:
                logger.error(
                    "Dropping pending remediation nmid=%s user=%s after %.0f min "
                    "(still failing: %s); message remains contained in Junk.",
                    nmid, recipient, age_min, exc,
                )
            else:
                still_pending.append(item)

    try:
        save_pending(still_pending)
    except Exception as exc:
        logger.error("Could not save pending remediations: %s", exc)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
 
def parse_verdict(response: dict) -> dict:
    """Pull the model's JSON verdict out of the chat-completions response.

    The model is asked to return:
        {"True/False": "...", "Confidence Rating": "...", "Justification": "..."}
    but it may wrap that JSON in ```json ... ``` fences, and "True/False" may
    arrive as a real boolean or as a string. Handle all of those here.

    Fail-safe: if the verdict can't be parsed (empty content, non-JSON, missing
    keys), return a threat verdict so the message is still quarantined, and set
    parse_error so the caller can log why rather than silently skipping it.
    """
    try:
        content = response["choices"][0]["message"]["content"]

        # Strip markdown code fences if the model added them.
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip()).strip()

        data = json.loads(content)

        # Accept either capitalisation of the key, and bool or string values.
        raw = data.get("True/False", data.get("True/false", False))
        is_threat = str(raw).strip().lower() == "true"

        return {
            "is_threat":     is_threat,
            "confidence":    data.get("Confidence Rating", "N/A"),
            "justification": data.get("Justification", ""),
            "parse_error":   False,
        }
    except Exception as exc:
        logger.warning("Could not parse model verdict (%s); failing safe to threat.", exc)
        return {
            "is_threat":     True,
            "confidence":    "N/A",
            "justification": (
                "Automated verdict could not be read; message quarantined "
                "as a precaution. Please consult your IT admin."
            ),
            "parse_error":   True,
        }


def parse_email(msg: dict) -> dict:
    """Extract the phishing-relevant fields from a Microsoft Graph message.

    The body is reduced to plain text and the headers are filtered down to a
    small useful set, so the payload we forward to the model stays compact.
    URLs are pulled from the *raw* HTML so links inside href="..." attributes
    are not lost when the markup is stripped.
    """
    body_obj = msg.get("body", {})
    raw_body = body_obj.get("content", "")
    return {
        "sender":   _extract_address(msg.get("from", {})),
        "receiver": _extract_recipients(msg.get("toRecipients", [])),
        "date":     _normalise_date(msg.get("receivedDateTime", "")),
        "subject":  msg.get("subject", ""),
        "body":     _extract_body(body_obj),
        "urls":     _extract_urls(raw_body),
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
    """Return the message body as trimmed plain text.

    Graph usually returns full HTML with repeated inline CSS, which wastes an
    enormous amount of the model's context. We strip it to readable text and
    cap the length so the forwarded payload stays small.
    """
    text = _html_to_text(body_obj.get("content", ""))
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS] + " …[truncated]"
    return text


def _html_to_text(raw: str) -> str:
    """Best-effort HTML -> plain text without extra dependencies."""
    if not raw:
        return ""
    # Drop <script>/<style> blocks entirely (content and all).
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    # Turn line-break and common block-closing tags into newlines.
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    # Remove all remaining tags.
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode entities (&nbsp;, &amp;, …) and normalise whitespace.
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _extract_urls(text: str) -> list:
    return list(set(re.findall(r'https?://[^\s<>"\')\]]*', text)))


def _extract_headers(raw_headers: list) -> dict:
    """Keep only the headers useful for phishing analysis.

    Drops the bulky, low-signal fields (antispam blobs, routing and
    diagnostic X-MS-Exchange-* headers, etc.) that otherwise dominate the
    prompt. Matching is case-insensitive.
    """
    return {
        h["name"]: h["value"]
        for h in raw_headers
        if "name" in h and "value" in h
        and h["name"].lower() in _USEFUL_HEADERS
    }


def _header_ci(headers: dict, name: str) -> str:
    """Case-insensitive lookup into a parsed headers dict."""
    name = name.lower()
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return ""
 
 
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