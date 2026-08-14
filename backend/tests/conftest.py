import base64
import os
from pathlib import Path


TEST_DB = Path(__file__).resolve().parent.parent / "test_rights.db"
if TEST_DB.exists():
    TEST_DB.unlink()

test_signing_key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("=")
test_webhook_key = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode("ascii").rstrip("=")

# Tests must not inherit deployment credentials or production safety modes from
# Docker Compose, a developer shell, or CI secrets.
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{TEST_DB}",
        "DEMO_MODE": "true",
        "MOCK_INTEGRATIONS": "true",
        "ALLOW_DEV_IDENTITY_HEADERS": "true",
        "ALLOW_DEV_MAGIC_LINKS": "true",
        "CORS_ALLOW_ORIGINS": "http://test",
        "RATE_LIMIT": "1000/minute",
        "RIGHTS_MAGIC_LINK_SECRET": "test-secret",
        "NODE_ID": "urn:clef:rights-node:test",
        "NODE_OPERATOR_EMAILS": "operator@example.com",
        "NODE_SIGNING_PRIVATE_KEY_B64": test_signing_key,
        "WEBHOOK_ENCRYPTION_KEY_B64": test_webhook_key,
        "WEBHOOK_ALLOW_PRIVATE_TARGETS": "false",
        "MAILGUN_API_KEY": "",
        "MLC_ENABLED": "false",
        "MLC_USERNAME": "",
        "MLC_PASSWORD": "",
        "MLC_AUTHORIZED_CAPABILITIES": "",
        "DDEX_ENABLED": "false",
        "DDEX_IMPLEMENTATION_LICENSE_CONFIRMED": "false",
        "DDEX_LIVE_MESSAGES": "false",
        "DDEX_AUTHORIZED_CAPABILITIES": "",
        "DDEX_MWL_XSD_PATH": "",
        "MUSICBRAINZ_ENABLED": "false",
        "OPENROUTER_API_KEY": "",
    }
)
