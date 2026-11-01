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
    client = MLCClient("member@example.com", "fixture-private-password", session=session)

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


def test_mlc_client_resolves_recording_song_codes_to_work_iswcs():
    session = FakeSession(
        [
            _response(200, {"idToken": "token-1", "expiresIn": 3600}),
            _response(
                200,
                [
                    {
                        "mlcSongCode": "WORK-1",
                        "iswc": "T1234567890",
                        "primaryTitle": "Example Work",
                    }
                ],
            ),
        ]
    )
    client = MLCClient("member@example.com", "fixture-private-password", session=session)

    works = client.get_works([" WORK-1 ", "WORK-1"])

    assert works[0]["iswc"] == "T1234567890"
    assert session.calls[1][0] == "https://public-api.themlc.com/works"
    assert session.calls[1][1]["json"] == [{"mlcsongCode": "WORK-1"}]

    with pytest.raises(MLCQueryError, match="At least one"):
        client.get_works([])
    with pytest.raises(MLCQueryError, match="limited to 100"):
        client.get_works([f"WORK-{index}" for index in range(101)])


def test_mlc_client_refreshes_once_after_unauthorized_search():
    session = FakeSession(
        [
            _response(200, {"idToken": "token-1", "expiresIn": 3600}),
            _response(401, {"error": "expired"}),
            _response(200, {"idToken": "token-2", "expiresIn": 3600}),
            _response(200, [{"isrc": "USAAA2600001"}]),
        ]
    )
    client = MLCClient("member@example.com", "fixture-private-password", session=session)

    assert client.search_recordings(isrc=" USAAA2600001 ") == [
        {"isrc": "USAAA2600001"}
    ]
    assert session.calls[1][1]["headers"]["Authorization"] == "Bearer token-1"
    assert session.calls[3][1]["headers"]["Authorization"] == "Bearer token-2"


def test_mlc_client_fails_closed_with_safe_transport_and_protocol_errors():
    unavailable = FakeSession([requests.ConnectionError("fixture-private-password leaked upstream")])
    client = MLCClient("member@example.com", "fixture-private-password", session=unavailable)
    with pytest.raises(MLCTransportError) as failure:
        client.search_songcode(title="Example")
    assert "fixture-private-password" not in str(failure.value)
    assert client.reachable is False

    malformed = FakeSession(
        [
            _response(200, {"idToken": "token", "expiresIn": 3600}),
            _response(200, {"unexpected": "shape"}),
        ]
    )
    with pytest.raises(MLCProtocolError, match="result list"):
        MLCClient("member@example.com", "fixture-private-password", session=malformed).search_songcode(
            title="Example"
        )

    empty = FakeSession([])
    with pytest.raises(MLCQueryError, match="title or writer"):
        MLCClient("member@example.com", "fixture-private-password", session=empty).search_songcode()


@pytest.mark.parametrize("status", [200, 204])
def test_mlc_client_only_accepts_explicit_no_content_as_no_results(status):
    empty = _response(status, None)
    empty.raw = io.BytesIO(b"")
    session = FakeSession([_response(200, {"idToken": "token", "expiresIn": 3600}), empty])
    client = MLCClient("member@example.com", "fixture-private-password", session=session)
    if status == 204:
        assert client.search_recordings(isrc="USAAA2600001") == []
    else:
        with pytest.raises(MLCProtocolError, match="non-JSON"):
            client.search_recordings(isrc="USAAA2600001")


def test_mlc_adapter_reports_live_reachability_without_expanding_authority():
    adapter = MLCAdapter(
        enabled=True,
        username="member@example.com",
        password="fixture-private-password",
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
        MLCClient("member@example.com", "fixture-private-password", session=redirected).search_songcode(
            title="Example"
        )
    assert redirected.calls[0][1]["allow_redirects"] is False
    assert redirected.calls[0][1]["stream"] is True

    oversized = FakeSession([_response(200, [{"payload": "x" * 100}])])
    client = MLCClient(
        "member@example.com",
        "fixture-private-password",
        session=oversized,
        max_response_bytes=32,
    )
    client._id_token = "already-authenticated"
    client._token_expires_at = float("inf")
    with pytest.raises(MLCProtocolError, match="size limit"):
        client.search_songcode(title="Example")
