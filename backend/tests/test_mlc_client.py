import json
import io

import pytest
import requests

from services.adapters.mlc import MLCAdapter
from services.mlc_client import (
    MLCClient,
    MLCProtocolError,
    MLCQueryError,
    MLCTransportError,
)


def _response(status: int, payload) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://public-api.themlc.com/test"
    response.headers["Content-Type"] = "application/json"
    content = json.dumps(payload).encode("utf-8")
    response.raw = io.BytesIO(content)
    response._content = False
    response._content_consumed = False
    return response


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_mlc_client_reuses_token_and_normalizes_search_without_logging_credentials():
    session = FakeSession(
        [
            _response(200, {"idToken": "token-1", "expiresIn": 3600}),
            _response(200, [{"mlcSongCode": "WORK-1"}]),
            _response(200, {"results": [{"mlcSongCode": "WORK-2"}]}),
        ]
    )
    client = MLCClient("member@example.com", "private-password", session=session)

    first = client.search_songcode(title="  Example Work  ")
    second = client.search_songcode(writer_lastname="  Writer  ")

    assert first == [{"mlcSongCode": "WORK-1"}]
    assert second == [{"mlcSongCode": "WORK-2"}]
    assert [call[0] for call in session.calls].count(
        "https://public-api.themlc.com/oauth/token"
    ) == 1
    assert session.calls[1][1]["json"] == {"title": "Example Work"}
    assert session.calls[2][1]["json"] == {
        "writers": [{"writerLastName": "Writer"}]
    }
    assert client.reachable is True
    assert client.last_verified_at is not None


def test_mlc_client_refreshes_once_after_unauthorized_search():
    session = FakeSession(
        [
            _response(200, {"idToken": "token-1", "expiresIn": 3600}),
            _response(401, {"error": "expired"}),
            _response(200, {"idToken": "token-2", "expiresIn": 3600}),
            _response(200, [{"isrc": "USAAA2600001"}]),
        ]
    )
    client = MLCClient("member@example.com", "private-password", session=session)

    assert client.search_recordings(isrc=" USAAA2600001 ") == [
        {"isrc": "USAAA2600001"}
    ]
    assert session.calls[1][1]["headers"]["Authorization"] == "Bearer token-1"
    assert session.calls[3][1]["headers"]["Authorization"] == "Bearer token-2"


def test_mlc_client_fails_closed_with_safe_transport_and_protocol_errors():
    unavailable = FakeSession([requests.ConnectionError("private-password leaked upstream")])
    client = MLCClient("member@example.com", "private-password", session=unavailable)
    with pytest.raises(MLCTransportError) as failure:
        client.search_songcode(title="Example")
    assert "private-password" not in str(failure.value)
    assert client.reachable is False

    malformed = FakeSession(
        [
            _response(200, {"idToken": "token", "expiresIn": 3600}),
            _response(200, {"unexpected": "shape"}),
        ]
    )
    with pytest.raises(MLCProtocolError, match="result list"):
        MLCClient("member@example.com", "private-password", session=malformed).search_songcode(
            title="Example"
        )

    empty = FakeSession([])
    with pytest.raises(MLCQueryError, match="title or writer"):
        MLCClient("member@example.com", "private-password", session=empty).search_songcode()


def test_mlc_adapter_reports_live_reachability_without_expanding_authority():
    adapter = MLCAdapter(
        enabled=True,
        username="member@example.com",
        password="private-password",
        base_url="https://public-api.themlc.com",
        authorized_capabilities={"catalog_lookup"},
    )
    assert adapter.client is not None
    adapter.client.reachable = True
    adapter.client.last_verified_at = "2026-07-13T12:00:00+00:00"

    capabilities = {row.name: row for row in adapter.capabilities()}
    assert capabilities["catalog_lookup"].authorized is True
    assert capabilities["catalog_lookup"].reachable is True
    assert capabilities["catalog_lookup"].last_verified_at == "2026-07-13T12:00:00+00:00"
    assert capabilities["ownership_evidence_read"].authorized is False


def test_mlc_client_refuses_redirects_and_bounds_streamed_response_bytes():
    redirected = FakeSession([_response(302, {"location": "elsewhere"})])
    with pytest.raises(MLCTransportError, match="authentication returned HTTP 302"):
        MLCClient("member@example.com", "private-password", session=redirected).search_songcode(
            title="Example"
        )
    assert redirected.calls[0][1]["allow_redirects"] is False
    assert redirected.calls[0][1]["stream"] is True

    oversized = FakeSession([_response(200, [{"payload": "x" * 100}])])
    client = MLCClient(
        "member@example.com",
        "private-password",
        session=oversized,
        max_response_bytes=32,
    )
    client._id_token = "already-authenticated"
    client._token_expires_at = float("inf")
    with pytest.raises(MLCProtocolError, match="size limit"):
        client.search_songcode(title="Example")
