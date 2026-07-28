import os
from azure.communication.email import EmailClient


def sendEmail(user_name, email_subject, justification_reason, confidence_rating="N/A"):

    # retry_total=0 disables the SDK's automatic retries. On an ACS 429 the
    # send fails fast with a single attempt (the caller logs it and moves on)
    # instead of hammering the endpoint 4x and deepening the rate-limit window.
    client = EmailClient.from_connection_string(
        os.environ["COMMUNICATION_SERVICES_CONNECTION_STRING"],
        retry_total=0,
    )

    content = {
        "subject": "Possible Phishing Email",
        "plainText": (
            f"The following email: {email_subject} is suspected to be phishing "
            f"(confidence: {confidence_rating}) for the following reason: "
            f"{justification_reason}. It has been moved to your Junk Email folder. "
            f"Please consult your IT admin to have it released."
        ),
    }

    message = {
        "senderAddress": os.environ["EMAIL_SENDER_ADDRESS"],
        "recipients": {
            "to": [{"address": user_name}],
        },
        "content": content,
    }

    poller = client.begin_send(message)
    result = poller.result()
    return result["status"]


ADMIN_ADDRESS = "admin@onthehooks.com"


def sendIncidentReportEmail(email_subject, report):
    """Send the incident-response report to the admin account."""
    import json

    client = EmailClient.from_connection_string(
        os.environ["COMMUNICATION_SERVICES_CONNECTION_STRING"],
        retry_total=0,
    )

    content = {
        "subject": f"Incident Response: {email_subject}",
        "plainText": (
            f"A phishing email ('{email_subject}') was detected and contained. "
            f"Incident response information:\n\n"
            f"{json.dumps(report, default=str, indent=2)}"
        ),
    }

    message = {
        "senderAddress": os.environ["EMAIL_SENDER_ADDRESS"],
        "recipients": {
            "to": [{"address": ADMIN_ADDRESS}],
        },
        "content": content,
    }

    poller = client.begin_send(message)
    result = poller.result()
    return result["status"]