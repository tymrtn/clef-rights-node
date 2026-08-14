from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger("clef.mlc")


class MLCClientError(RuntimeError):
    """Base class for safe, credential-free MLC client failures."""


class MLCAuthenticationError(MLCClientError):
    pass


class MLCQueryError(MLCClientError):
    pass


class MLCTransportError(MLCClientError):
    pass


class MLCProtocolError(MLCClientError):
    pass


class MLCClient:
    """Bounded MLC API client with token reuse, refresh, retries, and safe errors."""

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str = "https://public-api.themlc.com",
        *,
        connect_timeout_seconds: int = 5,
        read_timeout_seconds: int = 20,
        max_retries: int = 3,
        max_response_bytes: int = 5_000_000,
        session: requests.Session | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.timeout = (connect_timeout_seconds, read_timeout_seconds)
        self.max_response_bytes = max_response_bytes
        self._id_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()
        self.reachable: bool | None = None
        self.last_verified_at: str | None = None
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Clef-Rights-Node/0.4",
            }
        )
        if session is None:
            retry = Retry(
                total=max_retries,
                connect=max_retries,
                read=max_retries,
                status=max_retries,
                allowed_methods=frozenset({"POST"}),
                status_forcelist=(408, 425, 429, 500, 502, 503, 504),
                backoff_factor=0.5,
                respect_retry_after_header=True,
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)

    def _mark_reachable(self, reachable: bool) -> None:
        self.reachable = reachable
        self.last_verified_at = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )

    def _post(self, path: str, *, body: dict[str, Any], headers: dict[str, str] | None = None):
        try:
            response = self._session.post(
                f"{self.base_url}{path}",
                json=body,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as error:
            self._mark_reachable(False)
            raise MLCTransportError("MLC request could not reach the configured service") from error
        self._mark_reachable(True)
        try:
            declared_length = int(response.headers.get("Content-Length", "0"))
        except ValueError:
            declared_length = 0
        if declared_length > self.max_response_bytes:
            response.close()
            raise MLCProtocolError("MLC response exceeded the configured size limit")
        content = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=65_536):
                content.extend(chunk)
                if len(content) > self.max_response_bytes:
                    raise MLCProtocolError(
                        "MLC response exceeded the configured size limit"
                    )
        except requests.RequestException as error:
            self._mark_reachable(False)
            raise MLCTransportError("MLC response body could not be read") from error
        finally:
            response.close()
        response._content = bytes(content)
        response._content_consumed = True
        return response

    def _response_json(self, response: requests.Response) -> Any:
        try:
            return response.json()
        except (ValueError, requests.JSONDecodeError) as error:
            raise MLCProtocolError("MLC returned a non-JSON response") from error

    def _authenticate(self, *, force: bool = False) -> None:
        with self._token_lock:
            if (
                not force
                and self._id_token
                and time.time() < self._token_expires_at
            ):
                return
            response = self._post(
                "/oauth/token",
                body={"username": self.username, "password": self.password},
            )
            if response.status_code in {401, 403}:
                self._id_token = None
                raise MLCAuthenticationError("MLC credentials were rejected")
            if not 200 <= response.status_code < 300:
                raise MLCTransportError(
                    f"MLC authentication returned HTTP {response.status_code}"
                )
            data = self._response_json(response)
            if not isinstance(data, dict):
                raise MLCProtocolError("MLC authentication response must be an object")
            id_token = data.get("idToken")
            try:
                expires_in = int(data.get("expiresIn", 3600))
            except (TypeError, ValueError) as error:
                raise MLCProtocolError("MLC authentication expiry was invalid") from error
            if not isinstance(id_token, str) or not id_token.strip():
                raise MLCProtocolError("MLC authentication did not return an idToken")
            if expires_in <= 0:
                raise MLCProtocolError("MLC authentication returned an expired token")
            self._id_token = id_token.strip()
            self._token_expires_at = time.time() + max(1, expires_in - 60)

    def _authorization_headers(self) -> dict[str, str]:
        self._authenticate()
        return {"Authorization": f"Bearer {self._id_token}"}

    def _search(self, path: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._post(path, body=body, headers=self._authorization_headers())
        if response.status_code == 401:
            self._id_token = None
            self._token_expires_at = 0
            response = self._post(
                path,
                body=body,
                headers=self._authorization_headers(),
            )
        if response.status_code in {400, 422}:
            raise MLCQueryError("MLC rejected the search criteria")
        if response.status_code in {401, 403}:
            raise MLCAuthenticationError("MLC credentials were rejected")
        if not 200 <= response.status_code < 300:
            raise MLCTransportError(f"MLC search returned HTTP {response.status_code}")
        data = self._response_json(response)
        if isinstance(data, dict):
            data = data.get("results", data.get("data"))
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise MLCProtocolError("MLC search response did not contain a result list")
        logger.info("MLC catalog lookup succeeded path=%s results=%d", path, len(data))
        return data

    def search_songcode(
        self,
        title: str | None = None,
        writer_lastname: str | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {}
        normalized_title = (title or "").strip()
        normalized_writer = (writer_lastname or "").strip()
        if normalized_title:
            body["title"] = normalized_title
        if normalized_writer:
            body["writers"] = [{"writerLastName": normalized_writer}]
        if not body:
            raise MLCQueryError("A work title or writer surname is required")
        return self._search("/search/songcode", body)

    def search_recordings(
        self,
        artist: str | None = None,
        title: str | None = None,
        isrc: str | None = None,
    ) -> list[dict[str, Any]]:
        body = {
            key: value.strip()
            for key, value in {
                "artist": artist or "",
                "title": title or "",
                "isrc": isrc or "",
            }.items()
            if value.strip()
        }
        if not body:
            raise MLCQueryError("An artist, title, or ISRC is required")
        return self._search("/search/recordings", body)
