import logging
import json
import requests
from azure.identity import DefaultAzureCredential

def run_kql_query(query: str, token: str) -> list:
    # Execute KQL against the Microsoft Graph API.
    api_url = "https://graph.microsoft.com/v1.0/security/runHuntingQuery"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        "query": query 
    }
    
    response = requests.post(api_url, headers=headers, json=payload)
        
    return response.json().get('value', [])


def run_phishing_investigation(message_id: str) -> dict:
    # Accepts a NetworkMessageId as a string and returns the investigation report as a dictionary.
    logging.info(f'Starting Automated Phishing Investigation for message ID: {message_id}')

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
        
        # Extract recipients
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

        # 5. Identity Sign-ins
        at_risk_users = list(set(recipients + clickers))
        
        if at_risk_users:
            users_formatted = "','".join(at_risk_users)
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

        return investigation_report

    except Exception as e:
        logging.error(f"Investigation failed for message ID {message_id}: {str(e)}")
        raise  # Re-raise the exception to be handled by the calling function