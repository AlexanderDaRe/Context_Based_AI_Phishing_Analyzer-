import azure.functions as func
import logging
import json
import requests
from azure.identity import DefaultAzureCredential

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

def run_kql_query(query: str, token: str) -> list:
    """Helper function to execute KQL against the Microsoft Graph API."""
    api_url = "https://graph.microsoft.com/v1.0/security/runHuntingQuery"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "query": query 
    }
    
    response = requests.post(api_url, headers=headers, json=payload)
    
    if not response.ok:
        error_details = response.text
        try:
            error_json = response.json()
            error_details = json.dumps(error_json, indent=2)
        except ValueError:
            pass
            
        raise Exception(f"Graph API Error {response.status_code}:\n{error_details}\n\nQuery Attempted:\n{query}")
        
    return response.json().get('value', [])

@app.route(route="PhishingInvestigation", methods=["POST"])
def PhishingInvestigation(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Starting Automated Phishing Investigation.')

    try:
        req_body = req.get_json()
        message_id = req_body.get('messageId')
    except ValueError:
        return func.HttpResponse("Invalid JSON payload.", status_code=400)

    if not message_id:
        return func.HttpResponse("Please pass a messageId.", status_code=400)

    try:
        credential = DefaultAzureCredential()
        token_obj = credential.get_token("https://graph.microsoft.com/.default")
        token = token_obj.token

        investigation_report = {
            "NetworkMessageId": message_id,
            "Summary": {}
        }

        # 1. Delivery & Source Events
        kql_delivery = f"""
        EmailEvents
        | where NetworkMessageId == '{message_id}'
        | project Timestamp, RecipientEmailAddress, DeliveryAction, DeliveryLocation, 
                  SenderFromAddress, SenderIPv4, Subject
        """
        delivery_data = run_kql_query(kql_delivery, token)
        investigation_report['EmailDeliveryAndSource'] = delivery_data
        
        # Extract recipients for later identity correlation
        recipients = [delivery.get('RecipientEmailAddress') for delivery in delivery_data if delivery.get('RecipientEmailAddress')]

        # 2. Attachments (IOCs)
        kql_attachments = f"""
        EmailAttachmentInfo
        | where NetworkMessageId == '{message_id}'
        | project FileName, FileType, SHA256
        """
        attachment_data = run_kql_query(kql_attachments, token)
        investigation_report['Attachments'] = attachment_data
        
        # 3. Embedded URLs (IOCs)
        kql_urls = f"""
        EmailUrlInfo
        | where NetworkMessageId == '{message_id}'
        | project Url, UrlDomain
        """
        url_data = run_kql_query(kql_urls, token)
        investigation_report['EmbeddedUrls'] = url_data

        # 4. Url Clicks
        kql_clicks = f"""
        UrlClickEvents
        | where NetworkMessageId == '{message_id}'
        | project Timestamp, AccountUpn, Url, ActionType, IPAddress
        """
        click_data = run_kql_query(kql_clicks, token)
        investigation_report['UrlClicks'] = click_data
        
        clickers = [click.get('AccountUpn') for click in click_data if click.get('AccountUpn')]

        # 5. Identity Sign-ins (Using recipients instead of read receipts)
        # We assume anyone who received it or clicked it needs their identity verified
        at_risk_users = list(set(recipients + clickers))
        
        if at_risk_users:
            users_formatted = "','".join(at_risk_users)
            # Utilizing EntraIdSignInEvents as seen in your table list
            kql_signins = f"""
            EntraIdSignInEvents
            | where AccountUpn in~ ('{users_formatted}')
            | where Timestamp > ago(7d)
            | summarize arg_max(Timestamp, *) by AccountUpn
            | project AccountUpn, LastSignInTime=Timestamp, IPAddress, City, Country, ClientAppUsed, RiskLevelDuringSignIn
            """
            signin_data = run_kql_query(kql_signins, token)
            investigation_report['IdentitySignIns'] = signin_data
        else:
            investigation_report['IdentitySignIns'] = "No users received the email or clicked links; sign-in investigation skipped."

        # Populate Top-Level Summary for fast triage
        investigation_report['Summary'] = {
            "TotalRecipients": len(recipients),
            "TotalUrlClicks": len(clickers),
            "AttachmentCount": len(attachment_data),
            "EmbeddedUrlCount": len(url_data)
        }

        return func.HttpResponse(
            json.dumps(investigation_report, indent=4),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Investigation failed: {str(e)}")
        return func.HttpResponse(f"Error during investigation: {str(e)}", status_code=500)