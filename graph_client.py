import os
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL  = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


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
        return {"Authorization": f"Bearer {self._get_token()}"}

    def get_inbox_messages_since(self, user_email: str, since: datetime) -> list:
        """Return messages received after *since*, oldest first."""
        # Graph expects UTC in ISO-8601 without microseconds
        since_str = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        url = (
            f"{GRAPH_BASE}/users/{user_email}/mailFolders/inbox/messages"
            f"?$filter=receivedDateTime gt {since_str}"
            f"&$orderby=receivedDateTime asc"
            f"&$select=id,subject,from,toRecipients,receivedDateTime,"
            f"body,internetMessageHeaders"
            f"&$top=50"
        )
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("value", [])
