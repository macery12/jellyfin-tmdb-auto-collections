from __future__ import annotations
from threading import Lock
import time
from typing import Any, Dict, Optional
import requests
from .cache import JsonCache

TMDB_API_URL = "https://api.themoviedb.org/3"
DEFAULT_LANGUAGE = "en-US"
DEFAULT_CACHE = "tmdb_cache.json"

DEFAULT_TIMEOUT = 5
CALL_INTERVAL_SECONDS = 0.25
tmdb_lock = Lock()

class TMDb:
    def __init__(
        self,
        api_key: str,
        language: str = DEFAULT_LANGUAGE,
        cache: Optional[JsonCache] = None,
        cache_file: str = DEFAULT_CACHE,
        logger=None,
        offline_mode: bool = False,
        debug: bool = False,
    ) -> None:
        self.api_key = api_key
        self.language = language
        self.logger = logger
        self.offline_mode = offline_mode
        self.debug = debug
        self.cache = cache or JsonCache(cache_file)
        self._last_call_ts = 0.0

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def _wait_interval(self) -> None:
        now = time.time()
        delta = now - self._last_call_ts
        if delta < CALL_INTERVAL_SECONDS:
            time.sleep(CALL_INTERVAL_SECONDS - delta)
        self._last_call_ts = time.time()

    def _request(self, path: str, movie_name: str = "", tmdb_id: Any = "") -> Optional[Dict[str, Any]]:
        if self.offline_mode:
            return None

        url = f"{TMDB_API_URL}{path}"
        attempts = 3

        for attempt in range(1, attempts + 1):
            try:
                with tmdb_lock:
                    self._wait_interval()

                    r = requests.get(
                        url,
                        params={"api_key": self.api_key, "language": self.language},
                        timeout=DEFAULT_TIMEOUT,
                    )

                    if r.status_code == 429:
                        retry_after = int(r.headers.get("Retry-After", "3"))
                        self._log(f"TMDb 429 Too Many Requests, waiting {retry_after}s")
                        time.sleep(retry_after)
                        continue

                    if r.status_code == 401:
                        raise RuntimeError("TMDb API key invalid")

                    r.raise_for_status()
                    data = r.json()

                return data

            except Exception as e:
                self._log(
                    f"TMDb error for '{movie_name}' (ID {tmdb_id}), "
                    f"attempt {attempt}/{attempts}: {e}"
                )
                time.sleep(1)

        self._log(f"Skipping '{movie_name}' after repeated TMDb failures.")
        return None


    def _filter_movie(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": data.get("id"),
            "title": data.get("title") or data.get("original_title"),
            "release_date": data.get("release_date"),
            "status": data.get("status"),
            "belongs_to_collection": data.get("belongs_to_collection"),
            "poster_path": data.get("poster_path"),
        }

    def _filter_collection(self, data: Dict[str, Any]) -> Dict[str, Any]:
        parts = []
        for item in data.get("parts", []):
            mid = item.get("id")
            if not mid:
                continue
            parts.append(
                {
                    "id": mid,
                    "title": item.get("title") or item.get("original_title"),
                    "release_date": item.get("release_date"),
                }
            )
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "poster_path": data.get("poster_path"),
            "parts": parts,
        }

    def get(self, path: str, movie_name: str = "", tmdb_id: Any = "") -> Optional[Dict[str, Any]]:
        if path.startswith("/movie/"):
            key_id = path.split("/")[-1]
            cached = self.cache.get_movie(key_id)
            if cached is not None:
                return cached
            raw = self._request(path, movie_name=movie_name, tmdb_id=tmdb_id)
            if not raw:
                return None
            filtered = self._filter_movie(raw)
            self.cache.set_movie(key_id, filtered)
            return filtered

        if path.startswith("/collection/"):
            key_id = path.split("/")[-1]
            cached = self.cache.get_collection(key_id)
            if cached is not None:
                return cached
            raw = self._request(path, movie_name=movie_name, tmdb_id=tmdb_id)
            if not raw:
                return None
            filtered = self._filter_collection(raw)
            self.cache.set_collection(key_id, filtered)
            return filtered

        return self._request(path, movie_name=movie_name, tmdb_id=tmdb_id)

    def get_poster(self, collection_id: int | str) -> Optional[bytes]:
        data = self.get(f"/collection/{collection_id}")
        if not data:
            return None

        poster = data.get("poster_path")
        if not poster:
            return None

        url = f"https://image.tmdb.org/t/p/original{poster}"

        try:
            self._wait_interval()
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.content
        except Exception as e:
            self._log(f"TMDb poster fetch error for collection {collection_id}: {e}")
            return None
