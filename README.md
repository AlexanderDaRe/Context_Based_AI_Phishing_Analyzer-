# EmailParserFunctionApp

Azure Function App that polls the Outlook inboxes of monitored users via Microsoft Graph,
parses each new email, and forwards a JSON payload to a configured endpoint.

---

## JSON payload shape

```json
{
  "sender":   "alice@example.com",
  "receiver": ["bob@example.com"],
  "date":     "2024-01-15T10:23:00+00:00",
  "subject":  "Hello",
  "body":     "Plain or HTML body text …",
  "urls":     ["https://example.com"],
  "headers":  {
    "Message-ID": "<abc@example.com>",
    "X-Mailer":   "Outlook 16.0"
  }
}
```

---

## Prerequisites

| What | Where |
|------|-------|
| Azure Function App (`EmailParserFunctionApp`) | Python 3.11 runtime, Consumption or Flex plan |
| App Registration (`EmailWebHook`) | Client-credentials secret created |
| Graph API permissions (application) | `Mail.Read`, `Mail.ReadWrite` — **admin consented** |
| Storage account | Used by the Functions runtime and for state blob |

---

## App Registration — required Graph permissions

In **Azure AD → App registrations → EmailWebHook → API permissions**, add:

| API | Permission | Type |
|-----|-----------|------|
| Microsoft Graph | `Mail.Read` | Application |
| Microsoft Graph | `Mail.ReadWrite` | Application |

Grant **admin consent** after adding them.

---

## Application settings (set in Azure Portal → Function App → Configuration)

| Setting | Value |
|---------|-------|
| `AZURE_TENANT_ID` | Your AAD tenant ID |
| `AZURE_CLIENT_ID` | EmailWebHook client (application) ID |
| `AZURE_CLIENT_SECRET` | EmailWebHook client secret value |
| `ENDPOINT_URL` | Full URL of the receiving endpoint |
| `ENDPOINT_JWT` | JWT token for the `Authorization: Bearer` header |

> **Never** commit real values to source control. Use Azure Key Vault references for secrets in production.

---

## Monitored users

Edit the `MONITORED_USERS` list at the top of `email_parser_function/__init__.py`:

```python
MONITORED_USERS = [
    "TestUser1@yourdomain.com",
    "TestUser2@yourdomain.com",
]
```

---

## Schedule

Default: every **2 minutes** (`0 */2 * * * *`).  
Change the cron expression in `email_parser_function/function.json → schedule`.

---

## Local development

```bash
pip install -r requirements.txt
# Fill in local.settings.json with real values
func start
```

---

## Deploy

```bash
func azure functionapp publish EmailParserFunctionApp
```
