import datetime
import re
import secrets
from typing import Tuple

import jwt

from services.notifications import NotificationProvider


class MagicLinkService:
    def __init__(self, secret: str, link_exp_minutes: int, session_ttl_minutes: int, notification_provider: NotificationProvider, base_url: str) -> None:
        self.secret = secret
        self.link_exp_minutes = link_exp_minutes
        self.session_ttl_minutes = session_ttl_minutes
        self.notification_provider = notification_provider
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _email(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Valid email required")
        email = value.strip().lower()
        if not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email):
            raise ValueError("Valid email required")
        return email

    def create_and_send_link(self, email: str) -> str:
        email = self._email(email)
        exp = datetime.datetime.utcnow() + datetime.timedelta(minutes=self.link_exp_minutes)
        # JWT dates have second precision; the nonce keeps simultaneous links distinct.
        token = jwt.encode({"email": email, "exp": exp, "jti": secrets.token_urlsafe(24)}, self.secret, algorithm="HS256")
        link = f"{self.base_url}/login?token={token}"
        if self.notification_provider.enabled:
            self.notification_provider.send(
                to_emails=[email],
                subject="Your Clef Rights Console Link",
                text=f"Your link (valid {self.link_exp_minutes} minutes): {link}",
            )
        return link

    def validate_token(self, token: str) -> Tuple[bool, str]:
        try:
            payload = jwt.decode(
                token, self.secret, algorithms=["HS256"],
                options={"require": ["exp", "email"]},
            )
            return True, self._email(payload["email"])
        except jwt.ExpiredSignatureError:
            return False, "Token expired"
        except (jwt.InvalidTokenError, ValueError, TypeError):
            return False, "Invalid sign-in link"

    def create_session(self, email: str) -> dict:
        session_id = secrets.token_urlsafe(24)
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=self.session_ttl_minutes)
        return {"id": session_id, "email": email, "expires_at": expires_at.isoformat()}
