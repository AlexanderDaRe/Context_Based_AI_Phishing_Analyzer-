"""
shared/incident_response.py

Early-stage phishing incident response. Given the Defender NetworkMessageId of
a detected phishing email, runs a series of Microsoft Defender Advanced Hunting
(KQL) queries via Microsoft Graph to gather delivery events, attachment and URL
IOCs, click events, and sign-in context for at-risk users, and returns a
triage report.

This is the consolidated version of the standalone PhishingInvestigation
function, adapted to run inline in the timer pipeline and to reuse the existing
GraphClient (app-only client-credentials token) instead of DefaultAzureCredential.

Auth: the app registration used by GraphClient must be granted the
ThreatHunting.Read.All application permission (with admin consent) in addition
to the Mail.* permissions used elsewhere. Advanced Hunting also requires the
tenant to have Microsoft Defender for Office 365 / Microsoft 365 Defender.
"""

import os
import json
import logging
from datetime import datetime, timezone

from shared.graph_client import GraphClient

logger = logging.getLogger(__name__)

# Blob container where IR reports are archived as durable artifacts.
REPORT_CONTAINER = "incident-reports"


def run_incident_response(network_message_id: str, graph: GraphClient = None) -> dict:
    """Build an early-stage incident-response report for a phishing email.

    *network_message_id* is the Defender NetworkMessageId (a GUID) taken from
    the X-MS-Exchange-Organization-Network-Message-Id header. It is NOT the
    Graph mail message id. Pass an existing *graph* to reuse its token; one is
    created if omitted.
    """
    graph = graph or GraphClient()

    report = {
        "NetworkMessageId": network_message_id,
        "Summary": {},
    }

    # 1. Delivery & source events
    delivery_data = graph.run_hunting_query(f"""
        EmailEvents
        | where NetworkMessageId == '{network_message_id}'
        | project Timestamp, RecipientEmailAddress, DeliveryAction, DeliveryLocation,
                  SenderFromAddress, SenderIPv4, Subject
        """)
    report["EmailDeliveryAndSource"] = delivery_data

    # Recipients drive the later identity correlation.
    recipients = [
        d.get("RecipientEmailAddress")
        for d in delivery_data
        if d.get("RecipientEmailAddress")
    ]

    # 2. Attachments (IOCs)
    report["Attachments"] = graph.run_hunting_query(f"""
        EmailAttachmentInfo
        | where NetworkMessageId == '{network_message_id}'
        | project FileName, FileType, SHA256
        """)

    # 3. Embedded URLs (IOCs)
    url_data = graph.run_hunting_query(f"""
        EmailUrlInfo
        | where NetworkMessageId == '{network_message_id}'
        | project Url, UrlDomain
        """)
    report["EmbeddedUrls"] = url_data

    # 4. URL clicks
    click_data = graph.run_hunting_query(f"""
        UrlClickEvents
        | where NetworkMessageId == '{network_message_id}'
        | project Timestamp, AccountUpn, Url, ActionType, IPAddress
        """)
    report["UrlClicks"] = click_data

    clickers = [c.get("AccountUpn") for c in click_data if c.get("AccountUpn")]

    # 5. Identity sign-ins for anyone who received or clicked (last 7 days).
    at_risk_users = list(set(recipients + clickers))
    if at_risk_users:
        users_formatted = "','".join(at_risk_users)
        report["IdentitySignIns"] = graph.run_hunting_query(f"""
            EntraIdSignInEvents
            | where AccountUpn in~ ('{users_formatted}')
            | where Timestamp > ago(7d)
            | summarize arg_max(Timestamp, *) by AccountUpn
            | project AccountUpn, LastSignInTime=Timestamp, IPAddress, City, Country,
                      ClientAppUsed, RiskLevelDuringSignIn
            """)
    else:
        report["IdentitySignIns"] = (
            "No users received the email or clicked links; "
            "sign-in investigation skipped."
        )

    # Top-level summary for fast triage.
    report["Summary"] = {
        "TotalRecipients":  len(recipients),
        "TotalUrlClicks":   len(clickers),
        "AttachmentCount":  len(report["Attachments"]),
        "EmbeddedUrlCount": len(url_data),
    }

    return report


def save_incident_report(network_message_id: str, report: dict) -> None:
    """Archive the IR report to blob storage as a durable artifact.

    Best-effort: logs and swallows storage errors so a persistence failure
    never breaks the detection pipeline (the report is also logged upstream).
    Reuses the AzureWebJobsStorage connection already used for run state.
    """
    try:
        from azure.storage.blob import BlobServiceClient

        svc = BlobServiceClient.from_connection_string(
            os.environ["AzureWebJobsStorage"]
        )
        try:
            svc.create_container(REPORT_CONTAINER)
        except Exception:
            pass  # already exists

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        blob = svc.get_blob_client(
            container=REPORT_CONTAINER,
            blob=f"{ts}_{network_message_id}.json",
        )
        blob.upload_blob(json.dumps(report, default=str, indent=2), overwrite=True)
    except Exception as exc:
        logger.error("Could not archive incident report to blob: %s", exc)