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
            # Try to format it nicely if it is JSON
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

        # Get list of users / Check email headers
        kql_delivery = f"""
        EmailEvents
        | where NetworkMessageId == '{message_id}'
        | project Timestamp, RecipientEmailAddress, DeliveryAction, DeliveryLocation, 
                  SenderFromAddress, SenderIPv4, Subject
        """
        delivery_data = run_kql_query(kql_delivery, token)
        investigation_report['EmailDeliveryAndSource'] = delivery_data

        # Did the user read the email?
        kql_read_status = f"""
        CloudAppEvents
        | where Application == 'Microsoft Exchange Online'
        | where ActionType == 'MailItemsAccessed'
        | where RawEventData has '{message_id}'
        | project Timestamp, AccountUpn, IPAddress
        | summarize FirstReadTime=min(Timestamp) by AccountUpn
        """
        read_data = run_kql_query(kql_read_status, token)
        investigation_report['UsersWhoReadEmail'] = read_data
        readers = [user['AccountUpn'] for user in read_data]

        # Attachment & Payload Hash (IOC)
        kql_attachments = f"""
        EmailAttachmentInfo
        | where NetworkMessageId == '{message_id}'
        | project FileName, FileType, SHA256, MalwareFilterVerdict
        """
        attachment_data = run_kql_query(kql_attachments, token)
        investigation_report['AttachmentsAndIOCs'] = attachment_data

        # Did the user click the link?
        kql_clicks = f"""
        UrlClickEvents
        | where NetworkMessageId == '{message_id}'
        | project Timestamp, AccountUpn, Url, ActionType, IPAddress
        """
        click_data = run_kql_query(kql_clicks, token)
        investigation_report['UrlClicks'] = click_data

        # Investigate sign-in events for identity
        # Only checking users who actually read or clicked the email
        at_risk_users = list(set(readers + [click['AccountUpn'] for click in click_data]))
        
        if at_risk_users:
            users_formatted = "','".join(at_risk_users)
            kql_signins = f"""
            AADSignInEventsBeta
            | where AccountUpn in ('{users_formatted}')
            | where Timestamp > ago(7d)
            | summarize arg_max(Timestamp, *) by AccountUpn
            | project AccountUpn, LastSignInTime=Timestamp, IPAddress, City, Country, ClientAppUsed, RiskLevelDuringSignIn
            """
            signin_data = run_kql_query(kql_signins, token)
            investigation_report['IdentitySignIns'] = signin_data
        else:
            investigation_report['IdentitySignIns'] = "No users read the email or clicked links; sign-in investigation skipped."

        # Return the consolidated investigation report
        return func.HttpResponse(
            json.dumps(investigation_report, indent=4),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Investigation failed: {str(e)}")
        return func.HttpResponse(f"Error during investigation: {str(e)}", status_code=500)