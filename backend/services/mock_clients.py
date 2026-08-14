from typing import Any, Dict, List, Optional


class MockMLCClient:
    """Deterministic mock responses when real MLC credentials are unavailable."""

    def search_songcode(self, title: Optional[str] = None, writer_lastname: Optional[str] = None) -> List[Dict[str, Any]]:
        return [
            {
                "mlcSongCode": "MOCK-SC-001",
                "workTitle": title or "Demo Work",
                "artist": "Demo Artist",
                "publishers": [{"publisherName": "Demo Pub"}],
                "writers": [{"writerFirstName": "Demo", "writerLastName": writer_lastname or "Writer"}],
            }
        ]

    def search_recordings(self, artist: Optional[str] = None, title: Optional[str] = None, isrc: Optional[str] = None) -> List[Dict[str, Any]]:
        return [
            {
                "title": title or "Demo Recording",
                "artist": artist or "Demo Artist",
                "mlcSongCode": "MOCK-SC-REC-001",
                "isrc": isrc or "MOCKISRC001",
                "publishers": [{"publisherName": "Demo Pub"}],
                "writers": [{"writerFirstName": "Demo", "writerLastName": "Writer"}],
            }
        ]


class MockMusicBrainzClient:
    """Simple mock for MusicBrainz search."""

    def search_recordings(
        self,
        artist: Optional[str] = None,
        title: Optional[str] = None,
        isrc: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "id": "mock-mbid-001",
                "title": title or "Demo Recording",
                "artist": artist or "Demo Artist",
                "isrc": isrc or "MOCKISRC001",
                "releases": [{"title": "Demo Release", "date": "2024-01-01"}],
                "isrc-list": [{"isrc": isrc or "MOCKISRC001"}],
                "artist-credit": [{"name": artist or "Demo Artist"}],
            }
        ]


def mock_intent(artist: str, intent: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic intent when LLM is unavailable."""
    title_fragment = (filters.get("title") if filters else None) or intent.split(" ")[0:2]
    tf = [title_fragment] if isinstance(title_fragment, str) else title_fragment
    return {
        "recordings": {
            "titleFragments": tf or ["demo"],
            "isrc": None,
        },
        "songcode": {
            "titleFragments": tf or ["demo"],
            "writerLastNames": [artist.split(" ")[-1]] if artist else [],
            "publisher": None,
            "years": None,
        },
        "chips": ["demo intent", "mocked response"],
        "summary": "Mock intent response (offline mode)",
        "warnings": ["Using mock intent; provide real API key to enable live parsing"],
        "fallback": True,
    }
