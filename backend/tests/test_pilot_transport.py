"""Exercise the real pilot client's credential boundary with local servers."""
import pytest

from test_deployment_web import local_server
from test_real_pilot_verifier import pilot


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_pilot_redirect_never_delivers_bearer_to_another_origin(status):
    received = []
    def sink(request):
        received.append(dict(request.headers))
        request.send_response(200)
        request.end_headers()
        request.wfile.write(b'{}')
    with local_server(sink) as other:
        def redirect(request):
            assert request.headers.get("Authorization") == "Bearer synthetic-token"
            request.send_response(status)
            request.send_header("Location", other + "/sink")
            request.end_headers()
        with local_server(redirect) as source:
            with pytest.raises(pilot.PilotVerificationError, match="different origin"):
                pilot.NodeClient(source, "synthetic-token").request("GET", "/evidence", authenticated=True)
    assert received == []


def test_pilot_same_origin_redirect_retains_authorization():
    def endpoint(request):
        assert request.headers.get("Authorization") == "Bearer synthetic-token"
        if request.path == "/evidence":
            request.send_response(302)
            request.send_header("Location", "/evidence/")
            request.end_headers()
        else:
            request.send_response(200)
            request.end_headers()
            request.wfile.write(b'{"ok":true}')
    with local_server(endpoint) as origin:
        assert pilot.NodeClient(origin, "synthetic-token").request("GET", "/evidence", authenticated=True) == {"ok": True}


@pytest.mark.parametrize("origin", ["https://example.test:bad", "https://example.test:0", "https://example.test\\@localhost", "https://example.test\n", "http://remote.example", "https://user:private@example.test"])
def test_pilot_rejects_unsafe_origin_without_echoing_secrets(origin):
    with pytest.raises(pilot.PilotVerificationError) as error:
        pilot.NodeClient(origin, "synthetic-token")
    assert "synthetic-token" not in str(error.value)
    assert "private" not in str(error.value)
