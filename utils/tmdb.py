from pathlib import Path
import time
import json
import requests

TMDB_API_URL = "https://api.themoviedb.org/3"
DEFAULT_LANGUAGE = "en-US"
DEFAULT_CACHE = "tmdb_cache.json"

DEFAULT_TIMEOUT = 5
CALL_INTERVAL_SECONDS = 0.25   # spacing between TMDb calls


class TMDb:
    def __init__(
        self,
        api_key,
        language=DEFAULT_LANGUAGE,
        cache_file=DEFAULT_CACHE,
        logger=None,
        offline_mode=False,
    ):
        self.api_key = api_key
        self.language = language
        self.cache_file = Path(cache_file)
        self.logger = logger
        self.offline_mode = offline_mode

        self._last_call_ts = 0.0

        try:
            with self.cache_file.open("r", encoding="utf-8") as f:
                self.cache = json.load(f)
        except Exception:
            self.cache = {}

    # log helper
    def _log(self, msg):
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    # save cache file
    def _save_cache(self):
        try:
            with self.cache_file.open("w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            self._log(f"TMDb cache save failed: {e}")

    # spacing between TMDb calls
    def _wait_interval(self):
        now = time.time()
        delta = now - self._last_call_ts
        if delta < CALL_INTERVAL_SECONDS:
            time.sleep(CALL_INTERVAL_SECONDS - delta)
        self._last_call_ts = time.time()

    # GET with caching
    def get(self, path, movie_name="", tmdb_id=""):
        if self.offline_mode:
            return None

        if path in self.cache:
            return self.cache[path]

        url = f"{TMDB_API_URL}{path}"
        attempts = 3

        for attempt in range(1, attempts + 1):
            try:
                self._wait_interval()

                r = requests.get(
                    url,
                    params={"api_key": self.api_key, "language": self.language},
                    timeout=DEFAULT_TIMEOUT,
                )

                if r.status_code == 429:
                    retry = int(r.headers.get("Retry-After", "3"))
                    self._log(f"TMDb 429 Too Many Requests, waiting {retry}s")
                    time.sleep(retry)
                    continue

                if r.status_code == 401:
                    raise RuntimeError("TMDb API key invalid")

                r.raise_for_status()
                data = r.json()

                # only cache successful responses
                self.cache[path] = data
                self._save_cache()
                return data

            except Exception as e:
                self._log(
                    f"TMDb error for '{movie_name}' (ID {tmdb_id}), "
                    f"attempt {attempt}/{attempts}: {e}"
                )
                time.sleep(1)

        self._log(f"Skipping '{movie_name}' after repeated TMDb failures.")
        return None

    # poster fetch
    def get_poster(self, collection_id):
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
