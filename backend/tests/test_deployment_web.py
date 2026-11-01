import importlib.util
import io
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Thread
import urllib.error
import urllib.request

import pytest


SPEC = importlib.util.spec_from_file_location(
    "deployment_web_verifier", Path(__file__).resolve().parents[2] / "scripts/verify_deployment.py",
)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def test_cache_only_response_reproduces_missing_inherited_security_headers():
    errors = verifier.web_header_errors({"cache-control": "no-store"})
    assert any("CSP" in error for error in errors)
    assert any("x-content-type-options" in error for error in errors)
    assert verifier.web_header_errors({
        "cache-control": "no-store", "x-content-type-options": "nosniff",
        "x-frame-options": "DENY", "referrer-policy": "no-referrer",
        "content-security-policy": "default-src 'self'; script-src 'self'; frame-ancestors 'none'; object-src 'none'",
    }) == []


@pytest.mark.parametrize("status,body,accepted", [
    (413, b"<html>Request Entity Too Large</html>", False),
    (401, b'{"detail":"A session or bearer API credential is required"}', True),
    (401, b'{"detail":"Upstream proxy login required"}', False),
])
def test_large_upload_probe_requires_the_api_authentication_response(monkeypatch, status, body, accepted):
    def respond(request, **_kwargs):
        assert len(request.data) > 10 * 1024 * 1024
        raise urllib.error.HTTPError(request.full_url, status, "fixture", {}, io.BytesIO(body))

    monkeypatch.setattr(verifier, "safe_open", respond)
    if accepted:
        verifier.probe_catalog_upload("http://fixture.test")
    else:
        with pytest.raises(RuntimeError, match="authentication boundary"):
            verifier.probe_catalog_upload("http://fixture.test")


@pytest.mark.parametrize("url", [
    "http://remote.example", "http://127.1", "http://localhost.remote.example",
    "https://user:fixture-secret@example.test", "https://example.test?token=fixture-secret",
    "https://example.test#fragment", "https://example.test:0", "https://example.test:65536",
    "https://example.test:bad", "file:///tmp/private", "https://example.test\\@localhost",
    " https://example.test", "https://example.test\n", "https://[::1", "http://[::1%25lo0]",
])
def test_unsafe_deployment_urls_fail_before_transport(url):
    with pytest.raises(RuntimeError, match="HTTPS deployment URL"):
        verifier.validated_origin(url)


@pytest.mark.parametrize("url,origin", [
    ("https://example.test/api", ("https", "example.test", 443)),
    ("https://EXAMPLE.test:443", ("https", "example.test", 443)),
    ("http://localhost:9247", ("http", "localhost", 9247)),
    ("http://127.0.0.1:9247", ("http", "127.0.0.1", 9247)),
    ("http://[::1]:9247", ("http", "::1", 9247)),
])
def test_remote_https_and_explicit_local_http_supported(url, origin):
    assert verifier.validated_origin(url) == origin


@pytest.mark.parametrize("target", ["http://example.test/health", "https://other.test/health", "https://example.test:8443/health"])
def test_redirect_handler_rejects_downgrade_host_and_port_changes(target):
    request = urllib.request.Request("https://example.test/readiness", headers={"X-Session-Id": "fixture-session"})
    with pytest.raises(RuntimeError):
        verifier.SameOriginRedirect().redirect_request(request, None, 302, "fixture", {}, target)


@pytest.mark.parametrize("bad_flag", ["--api-url", "--web-url"])
def test_cli_validates_both_urls_before_credentials_or_network(monkeypatch, capsys, bad_flag):
    class SecretTrap(dict):
        def get(self, key, default=None):
            if key == "CLEF_OPERATOR_SESSION_ID":
                pytest.fail("operator credentials read before URL validation")
            return super().get(key, default)
    def transport(*_args, **_kwargs):
        pytest.fail("network contacted before both URLs passed validation")
    monkeypatch.setattr(verifier.os, "environ", SecretTrap())
    monkeypatch.setattr(verifier, "safe_open", transport)
    monkeypatch.setattr(sys, "argv", ["verify_deployment.py", "--skip-compose", "--require-readiness",
                                    bad_flag, "https://operator:fixture-secret@example.test"])
    assert verifier.main() == 1
    output = capsys.readouterr().out
    assert "fixture-secret" not in output
    assert json.loads(output)["ok"] is False


@contextmanager
def local_server(callback):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            callback(self)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_real_redirect_never_delivers_session_to_another_origin(status):
    received = []
    def sink(request):
        received.append(dict(request.headers))
        request.send_response(200)
        request.end_headers()
        request.wfile.write(b'{"ready":true}')
    with local_server(sink) as other:
        def redirect(request):
            assert request.headers.get("X-Session-Id") == "fixture-session"
            request.send_response(status)
            request.send_header("Location", other + "/stolen")
            request.end_headers()
        with local_server(redirect) as source:
            with pytest.raises(RuntimeError, match="different origin"):
                verifier.fetch_json(source + "/readiness", headers={"X-Session-Id": "fixture-session"})
    assert received == []


def test_real_same_origin_redirect_preserves_authorized_readiness():
    def endpoint(request):
        if request.path == "/readiness":
            request.send_response(302)
            request.send_header("Location", "/readiness/")
            request.end_headers()
        else:
            assert request.headers.get("X-Session-Id") == "fixture-session"
            request.send_response(200)
            request.end_headers()
            request.wfile.write(b'{"ready":true}')
    with local_server(endpoint) as source:
        assert verifier.fetch_json(source + "/readiness", headers={"X-Session-Id": "fixture-session"}) == {"ready": True}


def test_local_session_stays_local_when_environment_configures_a_proxy(monkeypatch):
    proxied = []
    def proxy(request):
        proxied.append(dict(request.headers))
        request.send_response(502)
        request.end_headers()
    def endpoint(request):
        assert request.headers.get("X-Session-Id") == "fixture-session"
        request.send_response(200)
        request.end_headers()
        request.wfile.write(b'{"ready":true}')
    with local_server(proxy) as proxy_url, local_server(endpoint) as source:
        monkeypatch.setenv("http_proxy", proxy_url)
        monkeypatch.setenv("HTTP_PROXY", proxy_url)
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setattr(verifier.urllib.request, "proxy_bypass", lambda _host: False)
        assert verifier.fetch_json(source, headers={"X-Session-Id": "fixture-session"}) == {"ready": True}
    assert proxied == []
