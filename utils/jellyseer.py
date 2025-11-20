from __future__ import annotations

from typing import Any, Dict, Optional

import requests


class JellyseerrClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 10, logger=None, debug: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.logger = logger
        self.debug = debug
        self.headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def _req(self, method: str, path: str, json_body: Any = None, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            r = requests.request(
                method,
                url,
                headers=self.headers,
                json=json_body,
                params=params,
                timeout=self.timeout,
            )
            r.raise_for_status()
            if r.text:
                try:
                    return r.json()
                except Exception:
                    return None
            return None
        except Exception as e:
            if self.debug:
                self._log(f"Jellyseerr {method} {url} failed: {e}")
            raise RuntimeError(str(e))

    def movie_details(self, tmdb_id: int) -> Any:
        return self._req("GET", f"/movie/{tmdb_id}")

    def is_movie_requested(self, tmdb_id: int) -> Any:
        try:
            data = self._req("GET", f"/media/{tmdb_id}")
            return data
        except RuntimeError:
            return None

    def request_movie(self, tmdb_id: int) -> Any:
        payload = {"mediaType": "movie", "tmdbId": tmdb_id}
        return self._req("POST", "/request", json_body=payload)
