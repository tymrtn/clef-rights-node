import os
from urllib.parse import urlparse
from services.source_reference import source_url_names_revision


class Settings:
    def __init__(self) -> None:
        self.PORT = int(os.getenv("PORT", "8081"))
        self.APP_ENV = os.getenv("APP_ENV", "development")
        self.DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes", "on")
        self.ALLOW_DEV_IDENTITY_HEADERS = os.getenv(
            "ALLOW_DEV_IDENTITY_HEADERS", "true" if self.DEMO_MODE else "false"
        ).lower() in ("1", "true", "yes", "on")
        self.ALLOW_DEV_MAGIC_LINKS = os.getenv(
            "ALLOW_DEV_MAGIC_LINKS", "true" if self.DEMO_MODE else "false"
        ).lower() in ("1", "true", "yes", "on")
        self.MOCK_INTEGRATIONS = os.getenv(
            "MOCK_INTEGRATIONS", "true" if self.DEMO_MODE else "false"
        ).lower() in ("1", "true", "yes", "on")

        # Auth/magic link
        self.RIGHTS_MAGIC_LINK_SECRET = os.getenv("RIGHTS_MAGIC_LINK_SECRET") or "dev-secret-change-me"
        self.RIGHTS_MAGIC_LINK_EXP_MINUTES = int(os.getenv("RIGHTS_MAGIC_LINK_EXP_MINUTES", "30"))
        self.RIGHTS_SESSION_TTL_MINUTES = int(os.getenv("RIGHTS_SESSION_TTL_MINUTES", "30"))
        self.NODE_OPERATOR_EMAILS = {
            value.strip().lower()
            for value in os.getenv("NODE_OPERATOR_EMAILS", "").split(",")
            if value.strip()
        }
        self.AUTH_SIGNUP_MODE = os.getenv("AUTH_SIGNUP_MODE", "open").strip().lower()
        if self.AUTH_SIGNUP_MODE not in {"open", "operator_only"}:
            raise RuntimeError("AUTH_SIGNUP_MODE must be open or operator_only")
        self.MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY")
        self.MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "mg.clef.pro")
        default_notification_provider = "mailgun" if self.MAILGUN_API_KEY else ("smtp" if os.getenv("SMTP_HOST") else "disabled")
        self.NOTIFICATION_PROVIDER = os.getenv("NOTIFICATION_PROVIDER", default_notification_provider).strip().lower()
        self.NOTIFICATION_FROM_EMAIL = os.getenv(
            "NOTIFICATION_FROM_EMAIL", f"Clef Rights <console@{self.MAILGUN_DOMAIN}>"
        ).strip()
        self.NOTIFICATION_CONNECT_TIMEOUT_SECONDS = int(os.getenv("NOTIFICATION_CONNECT_TIMEOUT_SECONDS", "5"))
        self.NOTIFICATION_READ_TIMEOUT_SECONDS = int(os.getenv("NOTIFICATION_READ_TIMEOUT_SECONDS", "15"))
        self.SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USERNAME = os.getenv("SMTP_USERNAME")
        self.SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
        self.SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
        self.EMAIL_DELIVERY_CONFIGURED = self.NOTIFICATION_PROVIDER in {"mailgun", "smtp"}
        self.CONSOLE_BASE_URL = os.getenv("CONSOLE_BASE_URL", "http://localhost:5174")
        self.SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

        # DB
        self.DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rights_console.db")
        self.DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
        self.DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

        # Node identity and receipt signing
        self.NODE_ID = os.getenv("NODE_ID", "urn:clef:rights-node:local")
        self.NODE_DEPLOYMENT_MODE = os.getenv(
            "NODE_DEPLOYMENT_MODE", "local_evaluation"
        ).strip().lower()
        self.SANDBOX_GUEST_ACCESS = os.getenv(
            "SANDBOX_GUEST_ACCESS", "false"
        ).lower() in ("1", "true", "yes", "on")
        self.NODE_SIGNING_PRIVATE_KEY_B64 = os.getenv("NODE_SIGNING_PRIVATE_KEY_B64")
        self.FEDERATION_ENABLED = os.getenv("FEDERATION_ENABLED", "false").lower() in ("1", "true", "yes", "on")
        self.FEDERATION_PUBLIC_ORIGIN = os.getenv("FEDERATION_PUBLIC_ORIGIN", "")
        self.FEDERATION_PEERS_JSON = os.getenv("FEDERATION_PEERS_JSON", "[]")
        self.FEDERATION_ALLOW_LOOPBACK = os.getenv("FEDERATION_ALLOW_LOOPBACK", "false").lower() in ("1", "true", "yes", "on")
        # The public key this node will sign with after a rotation; peers pin it ahead of the switch.
        self.NODE_NEXT_SIGNING_PUBLIC_KEY_B64 = os.getenv("NODE_NEXT_SIGNING_PUBLIC_KEY_B64", "")
        # Public keys this node signed with before a rotation; its older receipts still verify against them.
        self.NODE_RETIRED_SIGNING_PUBLIC_KEYS_B64 = os.getenv("NODE_RETIRED_SIGNING_PUBLIC_KEYS_B64", "")
        self.SOURCE_CODE_URL = (os.getenv("SOURCE_CODE_URL") or "").strip()
        self.SOURCE_CODE_REVISION = (os.getenv("SOURCE_CODE_REVISION") or "development").strip()

        # Durable webhook delivery. Development may derive an encryption key
        # from the local auth secret; staging and production require key separation.
        self.WEBHOOK_ENCRYPTION_KEY_B64 = os.getenv("WEBHOOK_ENCRYPTION_KEY_B64")
        self.WEBHOOK_ALLOW_PRIVATE_TARGETS = os.getenv(
            "WEBHOOK_ALLOW_PRIVATE_TARGETS", "false"
        ).lower() in ("1", "true", "yes", "on")
        self.WEBHOOK_DELIVERY_ENABLED = os.getenv(
            "WEBHOOK_DELIVERY_ENABLED", "true"
        ).lower() in ("1", "true", "yes", "on")
        self.WEBHOOK_MAX_ATTEMPTS = int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "6"))
        self.WEBHOOK_REQUEST_TIMEOUT_SECONDS = int(os.getenv("WEBHOOK_REQUEST_TIMEOUT_SECONDS", "10"))
        self.WEBHOOK_WORKER_INTERVAL_SECONDS = int(os.getenv("WEBHOOK_WORKER_INTERVAL_SECONDS", "10"))
        if not 1 <= self.WEBHOOK_MAX_ATTEMPTS <= 20:
            raise RuntimeError("WEBHOOK_MAX_ATTEMPTS must be between 1 and 20")
        if not 1 <= self.WEBHOOK_REQUEST_TIMEOUT_SECONDS <= 60:
            raise RuntimeError("WEBHOOK_REQUEST_TIMEOUT_SECONDS must be between 1 and 60")
        if not 1 <= self.WEBHOOK_WORKER_INTERVAL_SECONDS <= 300:
            raise RuntimeError("WEBHOOK_WORKER_INTERVAL_SECONDS must be between 1 and 300")

        # Signed permission expiry is a supervised singleton process. It runs
        # immediately on startup and then at this interval.
        self.EXPIRY_WORKER_INTERVAL_SECONDS = int(
            os.getenv("EXPIRY_WORKER_INTERVAL_SECONDS", "86400")
        )
        if not 60 <= self.EXPIRY_WORKER_INTERVAL_SECONDS <= 604800:
            raise RuntimeError(
                "EXPIRY_WORKER_INTERVAL_SECONDS must be between 60 and 604800"
            )

        # The MLC
        self.MLC_ENABLED = os.getenv("MLC_ENABLED", "false").lower() in ("1", "true", "yes", "on")
        self.MLC_USERNAME = os.getenv("MLC_USERNAME")
        self.MLC_PASSWORD = os.getenv("MLC_PASSWORD")
        self.MLC_BASE_URL = os.getenv("MLC_BASE_URL", "https://public-api.themlc.com")
        self.MLC_CONNECT_TIMEOUT_SECONDS = int(os.getenv("MLC_CONNECT_TIMEOUT_SECONDS", "5"))
        self.MLC_READ_TIMEOUT_SECONDS = int(os.getenv("MLC_READ_TIMEOUT_SECONDS", "20"))
        self.MLC_MAX_RETRIES = int(os.getenv("MLC_MAX_RETRIES", "3"))
        self.MLC_MAX_RESPONSE_BYTES = int(os.getenv("MLC_MAX_RESPONSE_BYTES", "5000000"))
        if not 1 <= self.MLC_CONNECT_TIMEOUT_SECONDS <= 30:
            raise RuntimeError("MLC_CONNECT_TIMEOUT_SECONDS must be between 1 and 30")
        if not 1 <= self.MLC_READ_TIMEOUT_SECONDS <= 120:
            raise RuntimeError("MLC_READ_TIMEOUT_SECONDS must be between 1 and 120")
        if not 0 <= self.MLC_MAX_RETRIES <= 8:
            raise RuntimeError("MLC_MAX_RETRIES must be between 0 and 8")
        if not 1024 <= self.MLC_MAX_RESPONSE_BYTES <= 50_000_000:
            raise RuntimeError("MLC_MAX_RESPONSE_BYTES must be between 1024 and 50000000")
        self.MLC_AUTHORIZED_CAPABILITIES = {
            value.strip()
            for value in os.getenv("MLC_AUTHORIZED_CAPABILITIES", "").split(",")
            if value.strip()
        }

        # DDEX is standards-based bilateral exchange, not a hosted API.
        self.DDEX_ENABLED = os.getenv("DDEX_ENABLED", "false").lower() in ("1", "true", "yes", "on")
        self.DDEX_IMPLEMENTATION_LICENSE_CONFIRMED = os.getenv(
            "DDEX_IMPLEMENTATION_LICENSE_CONFIRMED", "false"
        ).lower() in ("1", "true", "yes", "on")
        self.DDEX_DPID = os.getenv("DDEX_DPID")
        self.DDEX_PARTNER_DPID = os.getenv("DDEX_PARTNER_DPID")
        self.DDEX_SENDER_NAME = os.getenv("DDEX_SENDER_NAME")
        self.DDEX_PARTNER_NAME = os.getenv("DDEX_PARTNER_NAME")
        self.DDEX_PROFILE = os.getenv("DDEX_PROFILE")
        self.DDEX_MWL_XSD_PATH = os.getenv("DDEX_MWL_XSD_PATH")
        self.DDEX_LIVE_MESSAGES = os.getenv("DDEX_LIVE_MESSAGES", "false").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self.DDEX_AUTHORIZED_CAPABILITIES = {
            value.strip()
            for value in os.getenv("DDEX_AUTHORIZED_CAPABILITIES", "").split(",")
            if value.strip()
        }

        # OpenRouter intent parsing
        self.OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
        self.OPENROUTER_INTENT_MODEL = os.getenv("OPENROUTER_INTENT_MODEL", "openai/gpt-4o-mini")

        # MusicBrainz (OAuth optional - works with User-Agent only)
        self.MUSICBRAINZ_ENABLED = os.getenv("MUSICBRAINZ_ENABLED", "false").lower() in ("1", "true", "yes", "on")
        self.MUSICBRAINZ_CLIENT_ID = os.getenv("MUSICBRAINZ_CLIENT_ID")
        self.MUSICBRAINZ_CLIENT_SECRET = os.getenv("MUSICBRAINZ_CLIENT_SECRET")
        self.MUSICBRAINZ_BASE_URL = os.getenv("MUSICBRAINZ_BASE_URL", "https://musicbrainz.org/ws/2")

        # API & middleware
        origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:6482,http://localhost:5174")
        self.CORS_ALLOW_ORIGINS = [o.strip() for o in origins.split(",") if o.strip()]
        self.RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")

        # Logging
        self.STRUCTURED_LOGGING = os.getenv("STRUCTURED_LOGGING", "false").lower() in ("1", "true", "yes", "on")
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

        self._validate()

    def _validate(self) -> None:
        production_like = self.APP_ENV.lower() in {"staging", "production"}
        if self.NOTIFICATION_PROVIDER not in {"disabled", "mailgun", "smtp"}:
            raise RuntimeError("NOTIFICATION_PROVIDER must be disabled, mailgun, or smtp")
        if not 1 <= self.NOTIFICATION_CONNECT_TIMEOUT_SECONDS <= 30:
            raise RuntimeError("NOTIFICATION_CONNECT_TIMEOUT_SECONDS must be between 1 and 30")
        if not 1 <= self.NOTIFICATION_READ_TIMEOUT_SECONDS <= 120:
            raise RuntimeError("NOTIFICATION_READ_TIMEOUT_SECONDS must be between 1 and 120")
        if not self.NOTIFICATION_FROM_EMAIL or "\n" in self.NOTIFICATION_FROM_EMAIL or "\r" in self.NOTIFICATION_FROM_EMAIL:
            raise RuntimeError("NOTIFICATION_FROM_EMAIL must be a non-empty single-line mailbox")
        if self.NOTIFICATION_PROVIDER == "mailgun" and (not self.MAILGUN_API_KEY or not self.MAILGUN_DOMAIN):
            raise RuntimeError("Mailgun email delivery requires MAILGUN_API_KEY and MAILGUN_DOMAIN")
        if self.NOTIFICATION_PROVIDER == "smtp":
            if not self.SMTP_HOST or not 1 <= self.SMTP_PORT <= 65535:
                raise RuntimeError("SMTP email delivery requires SMTP_HOST and a valid SMTP_PORT")
            if self.SMTP_SECURITY not in {"none", "starttls", "implicit"}:
                raise RuntimeError("SMTP_SECURITY must be none, starttls, or implicit")
            if bool(self.SMTP_USERNAME) != bool(self.SMTP_PASSWORD):
                raise RuntimeError("SMTP_USERNAME and SMTP_PASSWORD must be configured together")
        allowed_deployment_modes = {
            "local_evaluation",
            "public_sandbox",
            "adopter_staging",
            "adopter_production",
        }
        if self.NODE_DEPLOYMENT_MODE not in allowed_deployment_modes:
            raise RuntimeError(
                "NODE_DEPLOYMENT_MODE must be local_evaluation, public_sandbox, "
                "adopter_staging, or adopter_production"
            )
        if self.SANDBOX_GUEST_ACCESS and self.NODE_DEPLOYMENT_MODE != "public_sandbox":
            raise RuntimeError(
                "SANDBOX_GUEST_ACCESS may only be enabled in public_sandbox mode"
            )
        sandbox_guest_only = (
            self.NODE_DEPLOYMENT_MODE == "public_sandbox"
            and self.SANDBOX_GUEST_ACCESS
        )
        if sandbox_guest_only and self.AUTH_SIGNUP_MODE != "operator_only":
            raise RuntimeError(
                "Public sandbox guest access requires AUTH_SIGNUP_MODE=operator_only"
            )
        if self.NODE_DEPLOYMENT_MODE == "public_sandbox" and (
            self.MLC_ENABLED
            or self.DDEX_ENABLED
            or self.DDEX_LIVE_MESSAGES
            or self.MUSICBRAINZ_ENABLED
            or bool(self.OPENROUTER_API_KEY)
            or bool(self.SLACK_WEBHOOK_URL)
        ):
            raise RuntimeError(
                "Public sandbox mode forbids live MLC, DDEX, MusicBrainz, "
                "OpenRouter, and Slack integrations"
            )
        if self.NODE_DEPLOYMENT_MODE == "public_sandbox" and self.WEBHOOK_DELIVERY_ENABLED:
            raise RuntimeError(
                "Public sandbox mode requires WEBHOOK_DELIVERY_ENABLED=false"
            )
        if self.NODE_DEPLOYMENT_MODE == "public_sandbox" and self.EMAIL_DELIVERY_CONFIGURED:
            raise RuntimeError("Public sandbox mode requires NOTIFICATION_PROVIDER=disabled")
        if self.SOURCE_CODE_URL:
            parsed_source_url = urlparse(self.SOURCE_CODE_URL)
            allowed_source_schemes = {"https"} if production_like else {"http", "https"}
            if (
                parsed_source_url.scheme not in allowed_source_schemes
                or not parsed_source_url.hostname
                or parsed_source_url.username
                or parsed_source_url.password
                or parsed_source_url.fragment
            ):
                raise RuntimeError(
                    "SOURCE_CODE_URL must be an HTTPS URL without credentials or a fragment in staging/production"
                )
        if not self.SOURCE_CODE_REVISION or len(self.SOURCE_CODE_REVISION) > 200:
            raise RuntimeError("SOURCE_CODE_REVISION must identify the deployed source revision")
        if not production_like:
            return
        if self.DEMO_MODE or self.MOCK_INTEGRATIONS or self.ALLOW_DEV_IDENTITY_HEADERS or self.ALLOW_DEV_MAGIC_LINKS:
            raise RuntimeError("Demo, mock, and development authentication modes are forbidden in staging/production")
        if self.RIGHTS_MAGIC_LINK_SECRET == "dev-secret-change-me" or len(self.RIGHTS_MAGIC_LINK_SECRET) < 32:
            raise RuntimeError("A strong RIGHTS_MAGIC_LINK_SECRET is required in staging/production")
        if self.DATABASE_URL.startswith("sqlite"):
            raise RuntimeError("A durable shared database is required in staging/production")
        if not self.NODE_OPERATOR_EMAILS and not sandbox_guest_only:
            raise RuntimeError("NODE_OPERATOR_EMAILS is required in staging/production")
        if not self.EMAIL_DELIVERY_CONFIGURED and not sandbox_guest_only:
            raise RuntimeError("Configured email delivery is required in staging/production")
        if self.NOTIFICATION_PROVIDER == "smtp" and (
            not self.SMTP_USERNAME or not self.SMTP_PASSWORD or self.SMTP_SECURITY == "none"
        ):
            raise RuntimeError("Production SMTP requires authentication and encrypted transport")
        if "*" in self.CORS_ALLOW_ORIGINS:
            raise RuntimeError("Wildcard CORS origins are forbidden in staging/production")
        if self.DDEX_LIVE_MESSAGES and self.APP_ENV.lower() != "production":
            raise RuntimeError("Live DDEX messages may only be enabled in production")
        if not self.WEBHOOK_ENCRYPTION_KEY_B64:
            raise RuntimeError("WEBHOOK_ENCRYPTION_KEY_B64 is required in staging/production")
        if self.WEBHOOK_ALLOW_PRIVATE_TARGETS:
            raise RuntimeError("Private webhook targets are forbidden in staging/production")
        if not self.SOURCE_CODE_URL or self.SOURCE_CODE_REVISION == "development":
            raise RuntimeError(
                "SOURCE_CODE_URL and SOURCE_CODE_REVISION are required in staging/production"
            )
        if not source_url_names_revision(self.SOURCE_CODE_URL, self.SOURCE_CODE_REVISION):
            raise RuntimeError("SOURCE_CODE_REVISION must be a full Git commit hash named in SOURCE_CODE_URL in staging/production")
        if self.MLC_ENABLED:
            if not self.MLC_USERNAME or not self.MLC_PASSWORD:
                raise RuntimeError("MLC_ENABLED requires MLC_USERNAME and MLC_PASSWORD")
            parsed_mlc_url = urlparse(self.MLC_BASE_URL)
            if parsed_mlc_url.scheme != "https" or not parsed_mlc_url.hostname:
                raise RuntimeError("MLC_BASE_URL must be an HTTPS origin in staging/production")
            if parsed_mlc_url.username or parsed_mlc_url.password:
                raise RuntimeError("MLC_BASE_URL must not contain credentials")
