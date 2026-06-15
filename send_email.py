
def sendEmail(user_name, email_subject, justification_reason):
    
    client = EmailClient.from_connection_string(
        os.environ["COMMUNICATION_SERVICES_CONNECTION_STRING"]
    )

    
    content = { "subject": "Possible Phising Email" ,
               "plainText": f"The following email: {email_subject} is suspected to be Phising for the following reason {justification_reason}, please consult your IT admin to have it released" }
    
    message = {
        "senderAddress": os.environ["EMAIL_SENDER_ADDRESS"],
        "recipients": {user_name},
        "content": content,
    }

    poller = client.begin_send(message)
    result = poller.result()
    return result["status"]