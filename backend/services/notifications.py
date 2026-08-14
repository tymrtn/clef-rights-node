from __future__ import annotations

from typing import Optional, Sequence

import requests


def send_mailgun_email(
    *,
    mailgun_api_key: Optional[str],
    mailgun_domain: str,
    from_email: str,
    to_emails: Sequence[str],
    subject: str,
    text: str,
) -> None:
    if not mailgun_api_key:
        return
    if not to_emails:
        return
    requests.post(
        f"https://api.mailgun.net/v3/{mailgun_domain}/messages",
        auth=("api", mailgun_api_key),
        data={
            "from": from_email,
            "to": list(to_emails),
            "subject": subject,
            "text": text,
        },
        timeout=15,
    )


def send_slack_message(*, slack_webhook_url: Optional[str], text: str) -> None:
    if not slack_webhook_url:
        return
    requests.post(slack_webhook_url, json={"text": text}, timeout=10)







