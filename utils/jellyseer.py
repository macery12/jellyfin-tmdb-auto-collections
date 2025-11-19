import requests

# CONSTANTS
DEFAULT_TIMEOUT = 10

class JellyseerrClient:
    def __init__(self, base_url, api_key, timeout=DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    # Internal request wrapper
    def _req(self, method, path, **kwargs):
        url = f"{self.base_url}{path}"

        try:
            r = requests.request(
                method,
                url,
                headers=self.headers,
                timeout=self.timeout,
                **kwargs,
            )
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Jellyseerr API error: {e}")

    # Public API
    def request_movie(self, tmdb_id):
        payload = {"mediaType": "movie", "mediaId": tmdb_id}
        return self._req("POST", "/request", json=payload)

    def search_movie(self, query):
        return self._req("GET", f"/search?query={query}")

    def get_status(self):
        return self._req("GET", "/status")

    def movie_details(self, tmdb_id):
        return self._req("GET", f"/movie/{tmdb_id}")

    def is_movie_requested(self, tmdb_id):
        try:
            return self._req("GET", f"/media/{tmdb_id}")
        except RuntimeError:
            return None
