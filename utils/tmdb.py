import time
import json
import requests

TMDB_API_URL = "https://api.themoviedb.org/3"
DEFAULT_LANGUAGE = "en-US"
DEFAULT_CACHE = "tmdb_cache.json"

DEFAULT_TIMEOUT = 5
CALL_INTERVAL_SECONDS = 0.2  # space out TMDb calls by 0.5s


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
        self.cache_file = cache_file
        self.logger = logger
        self.offline_mode = offline_mode

        self._last_call_ts = 0.0

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                self.cache = json.load(f)
        except Exception:
            self.cache = {}

    # Helpers
    def _log(self, msg):
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def _save_cache(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            self._log(f"TMDb cache save failed: {e}")

    def _wait_interval(self):
        """Ensure at least CALL_INTERVAL_SECONDS between remote requests."""
        now = time.time()
        delta = now - self._last_call_ts
        if delta < CALL_INTERVAL_SECONDS:
            sleep_time = CALL_INTERVAL_SECONDS - delta
            time.sleep(sleep_time)
        self._last_call_ts = time.time()

    # JSON GET with cache
    def get(self, path, movie_name="", tmdb_id=""):
        if self.offline_mode:
            return None

        # Use cache if present
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
        self.cache[path] = None
        self._save_cache()
        return None

    # Poster fetch 
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
