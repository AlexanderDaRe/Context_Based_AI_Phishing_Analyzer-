"""
shared/graph_client.py
Thin wrapper around Microsoft Graph for reading inbox messages.
Uses client-credentials flow (app-only) so no user interaction is needed.
"""

import os
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL  = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

# Fields we select for every message so parse_email() has what it needs.
_MESSAGE_SELECT = (
    "id,subject,from,toRecipients,receivedDateTime,body,internetMessageHeaders"
)


class GraphClient:

    def __init__(self):
        self._tenant_id     = os.environ["AZURE_TENANT_ID"]
        self._client_id     = os.environ["AZURE_CLIENT_ID"]
        self._client_secret = os.environ["AZURE_CLIENT_SECRET"]
        self._token = None

    def _get_token(self) -> str:
        if self._token:
            return self._token
        resp = requests.post(
            TOKEN_URL.format(tenant_id=self._tenant_id),
            data={
                "grant_type":    "client_credentials",
                "client_id":     self._client_id,
                "client_secret": self._client_secret,
                "scope":         "https://graph.microsoft.com/.default",
            },
            timeout=15,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict:
        # Default python-requests User-Agent, set explicitly.
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "User-Agent": f"python-requests/{requests.__version__}",
        }

    def get_inbox_messages_since(self, user_email: str, since: datetime) -> list:
        """Return messages received after *since*, oldest first."""
        since_str = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            f"{GRAPH_BASE}/users/{user_email}/mailFolders/inbox/messages"
            f"?$filter=receivedDateTime gt {since_str}"
            f"&$orderby=receivedDateTime asc"
            f"&$select={_MESSAGE_SELECT}"
            f"&$top=50"
        )
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("value", [])

    def run_hunting_query(self, query: str) -> list:
        """Run a Microsoft Defender Advanced Hunting (KQL) query via Graph.

        Requires the ThreatHunting.Read.All application permission.
        """
        url = f"{GRAPH_BASE}/security/runHuntingQuery"
        resp = requests.post(
            url,
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"query": query},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", data.get("value", []))

    def remediate_email(self, network_message_id: str, recipient_email: str,
                        action: str = "softDelete", severity: str = "medium",
                        display_name: str = "Auto-remediate phishing email",
                        description: str = "Flagged by automated phishing pipeline"
                        ) -> dict:
        """Remediate a delivered message via Microsoft Defender.

        *action* is one of: moveToQuarantine (holds the message in the Defender
        quarantine at security.microsoft.com), softDelete, hardDelete,
        moveToJunk, moveToInbox, moveToDeletedItems. Keyed on the Defender
        NetworkMessageId (a GUID, NOT the Graph mail id) plus the recipient.

        moveToQuarantine is an unknown-enum-member on the evolvable
        remediationAction enum, so we send Prefer: include-unknown-enum-members.

        Requires SecurityAnalyzedMessage.ReadWrite.All (app) and the message
        must have been analyzed by Microsoft Defender for Office 365. Returns
        202 Accepted; progress is tracked in the Defender Action center.

        A 409 "Duplicate remediation" is treated as success: Defender already has
        a remediation registered for this message (within its 30-minute rollup
        window), so there is nothing more to do.
        """
        url = f"{GRAPH_BASE}/security/collaboration/analyzedEmails/remediate"
        payload = {
            "displayName":          display_name,
            "description":          description,
            "severity":             severity,
            "action":               action,
            "remediateSendersCopy": False,
            "analyzedEmails": [
                {
                    "networkMessageId":      network_message_id,
                    "recipientEmailAddress": recipient_email,
                }
            ],
        }
        resp = requests.post(
            url,
            headers={
                **self._headers(),
                "Content-Type": "application/json",
                "Prefer": "include-unknown-enum-members",
            },
            json=payload,
            timeout=30,
        )
        # Duplicate = a remediation already exists for this message. Terminal
        # success, not a retryable error.
        if resp.status_code == 409 and "Duplicate remediation" in resp.text:
            return {
                "status_code":   409,
                "duplicate":     True,
                "action_center": resp.headers.get("Location", ""),
            }
        if not resp.ok:
            logger.error(
                "remediate_email %s is_graph=%s body=%s",
                resp.status_code,
                bool(resp.headers.get("request-id")),
                resp.text[:600],
            )
        resp.raise_for_status()
        return {
            "status_code":   resp.status_code,
            "duplicate":     False,
            "action_center": resp.headers.get("Location", ""),
        }

    def quarantine_message(self, user_email: str, message_id: str,
                           destination: str = "junkemail") -> dict:
        """Move a message out of the inbox (Graph-native fallback). Mail.ReadWrite."""
        url = f"{GRAPH_BASE}/users/{user_email}/messages/{message_id}/move"
        resp = requests.post(
            url,
            headers={**self._headers(), "Content-Type": "application/json"},
            json={"destinationId": destination},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
