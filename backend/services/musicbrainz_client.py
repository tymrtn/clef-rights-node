import time
from typing import Optional, Dict, Any, List
import requests
import base64


class MusicBrainzClient:
    """Client for MusicBrainz API with OAuth token caching."""

    def __init__(self, client_id: str, client_secret: str, base_url: str = "https://musicbrainz.org/ws/2"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._user_agent = "ClefRightsConsole/1.0 (https://clef.pro)"

    def _authenticate(self) -> None:
        """Get OAuth access token using client credentials (optional - MusicBrainz works with User-Agent only)."""
        # MusicBrainz API works with just User-Agent, but OAuth can provide higher rate limits
        if not self.client_id or not self.client_secret:
            return  # Skip OAuth if credentials not provided
        
        try:
            url = "https://musicbrainz.org/oauth2/token"
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": self._user_agent,
                },
                data={"grant_type": "client_credentials"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            access_token = data.get("access_token")
            expires_in = int(data.get("expires_in", 3600))
            if access_token:
                self._access_token = access_token
                self._token_expires_at = time.time() + max(60, expires_in - 60)
        except Exception as e:
            print(f"MusicBrainz OAuth failed (will use User-Agent only): {str(e)}")
            # Continue without OAuth - User-Agent is sufficient

    def _headers(self) -> Dict[str, str]:
        """Get headers with authentication and User-Agent."""
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }
        # Use OAuth token if available and valid
        if self.client_id and self.client_secret:
            if not self._access_token or time.time() >= self._token_expires_at:
                self._authenticate()
            if self._access_token:
                headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def search_recordings(
        self, 
        artist: Optional[str] = None, 
        title: Optional[str] = None, 
        isrc: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search for recordings in MusicBrainz.
        
        Args:
            artist: Artist name (supports artist-only search)
            title: Recording title (optional)
            isrc: ISRC code (optional)
            limit: Maximum number of results (default 100, max 100)
        
        Returns:
            List of recording objects with MBID, title, artist, release info, ISRCs
        """
        url = f"{self.base_url}/recording"
        query_parts = []
        
        if artist and artist.strip():
            query_parts.append(f'artist:"{artist.strip()}"')
        if title and title.strip():
            query_parts.append(f'recording:"{title.strip()}"')
        if isrc and isrc.strip():
            query_parts.append(f'isrc:{isrc.strip()}')
        
        if not query_parts:
            print("MusicBrainz recordings search skipped: no search parameters provided")
            return []
        
        query = " AND ".join(query_parts)
        params = {
            "query": query,
            "limit": min(limit, 100),  # MusicBrainz max is 100
            "fmt": "json",
            "inc": "releases+isrcs",  # Include release info and ISRCs
        }
        
        print(f"MusicBrainz recordings search: GET {url} with query: {query}")
        try:
            # Respect rate limit: 1 request per second
            time.sleep(1)
            
            resp = requests.get(url, params=params, headers=self._headers(), timeout=20)
            print(f"MusicBrainz recordings search status: {resp.status_code}")
            
            if resp.status_code == 503:
                print("MusicBrainz API rate limit exceeded or service unavailable")
                return []
            if resp.status_code == 404:
                return []
            
            resp.raise_for_status()
            data = resp.json()
            recordings = data.get("recordings", [])
            print(f"MusicBrainz recordings search returned {len(recordings)} results")
            return recordings
        except requests.exceptions.RequestException as e:
            print(f"MusicBrainz recordings search failed: {str(e)}")
            return []

    def search_artist_recordings(self, artist: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Convenience method to search all recordings by an artist.
        This is the primary use case for artist-only searches.
        """
        return self.search_recordings(artist=artist, limit=limit)

