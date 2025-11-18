import requests

class JellyseerrClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 10):
        """
        base_url: http(s)://your-jellyseerr-server/api/v1
        api_key: API Key from Jellyseerr
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}

    def _req(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        try:
            r = requests.request(
                method,
                url,
                headers=self.headers,
                timeout=self.timeout,
                **kwargs
            )
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Jellyseerr API error: {e}")

    # ---------------------------------------------------------
    # PUBLIC FUNCTIONS
    # ---------------------------------------------------------

    def request_movie(self, tmdb_id: int):
        """
        Create a request for a movie by TMDb ID.
        """
        payload = {
            "mediaType": "movie",
            "mediaId": tmdb_id,
        }
        return self._req("POST", "/request", json=payload)

    def search_movie(self, query: str):
        """
        Jellyseerr search for movies.
        """
        return self._req("GET", f"/search?query={query}")

    def get_status(self):
        """
        Returns Jellyseerr /status without needing auth.
        """
        return self._req("GET", "/status")
    
    def movie_details(self, tmdb_id: int):
        """
        Get movie details from Jellyseerr’s TMDb proxy.
        """
        return self._req("GET", f"/movie/{tmdb_id}")

    def is_movie_requested(self, tmdb_id: int):
        """
        Check if a movie is already requested or exists.
        """
        try:
            data = self._req("GET", f"/media/{tmdb_id}")
            return data
        except RuntimeError:
            return None
