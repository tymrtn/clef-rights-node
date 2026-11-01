import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/bootstrap_env.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_env", SCRIPT)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def _run(output: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output",
            str(output),
            "--node-slug",
            "test-adopter",
            "--console-url",
            "https://rights.example.test",
            "--source-url",
            "https://github.com/example/rights-node/tree/0123456789abcdef0123456789abcdef01234567",
            "--revision",
            "0123456789abcdef0123456789abcdef01234567",
            "--operator-emails",
            "operator@example.test",
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_bootstrap_generates_owner_only_smtp_adopter_environment(tmp_path):
    output = tmp_path / "adopter.env"
    result = _run(
        output,
        "--notification-provider",
        "smtp",
        "--smtp-host",
        "smtp.example.test",
        "--notification-from-email",
        "Rights Desk <rights@example.test>",
    )
    assert result.returncode == 0, result.stderr
    content = output.read_text(encoding="utf-8")
    assert "NODE_DEPLOYMENT_MODE=adopter_staging" in content
    assert "NOTIFICATION_PROVIDER=smtp" in content
    assert "SMTP_HOST=smtp.example.test" in content
    assert "SMTP_PASSWORD=" in content
    assert "NODE_SIGNING_PRIVATE_KEY_B64=" in content
    assert (os.stat(output).st_mode & 0o777) == 0o600


def test_bootstrap_public_sandbox_forbids_outbound_email(tmp_path):
    output = tmp_path / "sandbox.env"
    rejected = _run(
        output,
        "--deployment-mode",
        "public_sandbox",
        "--sandbox-guest-access",
        "--notification-provider",
        "smtp",
        "--smtp-host",
        "smtp.example.test",
    )
    assert rejected.returncode != 0
    assert "public_sandbox requires --notification-provider disabled" in rejected.stderr

    accepted = _run(
        output,
        "--deployment-mode",
        "public_sandbox",
        "--sandbox-guest-access",
        "--notification-provider",
        "disabled",
    )
    assert accepted.returncode == 0, accepted.stderr
    content = output.read_text(encoding="utf-8")
    assert "NOTIFICATION_PROVIDER=disabled" in content
    assert "WEBHOOK_DELIVERY_ENABLED=false" in content


def test_private_environment_is_mode_0600_before_atomic_replace(tmp_path, monkeypatch):
    output = tmp_path / "adopter.env"
    observed: dict[str, object] = {}
    real_replace = bootstrap.os.replace

    def inspect_then_replace(source, destination):
        observed["mode"] = os.stat(source).st_mode & 0o777
        observed["content"] = Path(source).read_text(encoding="utf-8")
        real_replace(source, destination)

    monkeypatch.setattr(bootstrap.os, "replace", inspect_then_replace)
    bootstrap.write_private_atomic(output, "generated private material\n")

    assert observed == {"mode": 0o600, "content": "generated private material\n"}
    assert output.read_text(encoding="utf-8") == "generated private material\n"
    assert (os.stat(output).st_mode & 0o777) == 0o600


def test_bootstrap_rejects_source_url_that_only_contains_revision_as_substring(tmp_path):
    result = _run(
        tmp_path / "adopter.env",
        "--source-url",
        "https://github.com/example/rights-node/tree/0123456789abcdef0123456789abcdef012345670-not-the-release",
        "--notification-provider",
        "smtp",
        "--smtp-host",
        "smtp.example.test",
    )
    assert result.returncode != 0
    assert "exact HTTPS path component" in result.stderr


@pytest.mark.parametrize("url", ["https://rights.example.test/login", "https://rights.example.test:0", "https://rights.example.test:bad", "https://[::1", "https://%65xample.test", "https://faß.test", "https://127.1"])
def test_console_url_rejection_precedes_environment_creation(tmp_path, url):
    output = tmp_path / "adopter.env"
    result = _run(output, "--console-url", url, "--smtp-host", "smtp.example.test")
    assert result.returncode != 0
    assert not output.exists()
    assert "Traceback" not in result.stderr


def test_console_origin_matches_browser_origin_and_preserves_source_path(tmp_path):
    output = tmp_path / "adopter.env"
    result = _run(output, "--console-url", "https://RIGHTS.EXAMPLE.TEST:443/", "--smtp-host", "smtp.example.test")
    assert result.returncode == 0, result.stderr
    values = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line and not line.startswith("#"))
    assert values["CORS_ALLOW_ORIGINS"] == "https://rights.example.test"
    assert values["CONSOLE_BASE_URL"] == "https://rights.example.test"
    assert "/tree/" in values["SOURCE_CODE_URL"]
    assert bootstrap.https_origin("https://[0:0:0:0:0:0:0:1]:8443/", "console URL") == "https://[::1]:8443"
