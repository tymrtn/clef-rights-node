import datetime
import secrets
from typing import Tuple

import jwt
import requests


class MagicLinkService:
    def __init__(self, secret: str, link_exp_minutes: int, session_ttl_minutes: int, mailgun_api_key: str | None, mailgun_domain: str, base_url: str) -> None:
        self.secret = secret
        self.link_exp_minutes = link_exp_minutes
        self.session_ttl_minutes = session_ttl_minutes
        self.mailgun_api_key = mailgun_api_key
        self.mailgun_domain = mailgun_domain
        self.base_url = base_url.rstrip("/")

    def create_and_send_link(self, email: str) -> str:
        email = email.strip().lower()
        if not ("@" in email and "." in email.split("@")[1]):
            raise ValueError("Valid email required")
        exp = datetime.datetime.utcnow() + datetime.timedelta(minutes=self.link_exp_minutes)
        token = jwt.encode({"email": email, "exp": exp}, self.secret, algorithm="HS256")
        link = f"{self.base_url}/login?token={token}"
        if self.mailgun_api_key:
            response = requests.post(
                f"https://api.mailgun.net/v3/{self.mailgun_domain}/messages",
                auth=("api", self.mailgun_api_key),
                data={
                    "from": f"Clef Rights <console@{self.mailgun_domain}>",
                    "to": [email],
                    "subject": "Your Clef Rights Console Link",
                    "text": f"Your link (valid {self.link_exp_minutes} minutes): {link}"
                },
                timeout=15,
            )
            response.raise_for_status()
        return link

    def validate_token(self, token: str) -> Tuple[bool, str]:
        try:
            payload = jwt.decode(token, self.secret, algorithms=["HS256"])
            return True, payload.get("email", "")
        except jwt.ExpiredSignatureError:
            return False, "Token expired"
        except Exception as e:
            return False, f"Invalid token: {str(e)}"

    def create_session(self, email: str) -> dict:
        session_id = secrets.token_urlsafe(24)
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=self.session_ttl_minutes)
        return {"id": session_id, "email": email, "expires_at": expires_at.isoformat()}
