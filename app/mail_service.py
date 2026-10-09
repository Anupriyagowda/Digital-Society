from flask import current_app
from flask_mail import Message

from app import mail


def send_app_email(recipient, subject, body, html=None):
    if not recipient:
        return False

    message = Message(
        subject=subject,
        recipients=[recipient],
        body=body,
        html=html,
    )
    try:
        mail.send(message)
    except Exception:
        current_app.logger.exception('Unable to send email to %s', recipient)
        return False
    return True
