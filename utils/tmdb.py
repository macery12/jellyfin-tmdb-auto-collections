import time
import json
import requests
from collections import deque


class TMDb:
    def __init__(
        self,
        api_key,
        language="en-US",
        cache_file="tmdb_cache.json",
        rate_limit=35,
        period=10,
        logger=None,
        offline_mode=False
    ):
        self.api_key = api_key
        self.language = language
        self.cache_file = cache_file
        self.logger = logger
        self.offline_mode = offline_mode

        # Rate limiter
        self.rate_limit = rate_limit
        self.period = period
        self.calls = deque()

        # Load cache
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def _log(self, msg):
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def _save_cache(self):
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    def _rate_wait(self):
        now = time.time()
        while self.calls and now - self.calls[0] > self.period:
            self.calls.popleft()

        if len(self.calls) >= self.rate_limit:
            sleep = self.period - (now - self.calls[0]) + 0.1
            time.sleep(sleep)

        self.calls.append(time.time())

    def get(self, path, movie_name="", tmdb_id=""):
        if self.offline_mode:
            return None

        key = path
        if key in self.cache:
            return self.cache[key]

        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                self._rate_wait()
                r = requests.get(
                    f"https://api.themoviedb.org/3{path}",
                    params={"api_key": self.api_key, "language": self.language},
                    timeout=5,
                )

                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", "3"))
                    self._log(f"TMDb rate limit hit, waiting {wait}s")
                    time.sleep(wait)
                    continue

                if r.status_code == 401:
                    raise RuntimeError("TMDb API key invalid")

                r.raise_for_status()
                data = r.json()

                self.cache[key] = data
                self._save_cache()
                return data

            except Exception as e:
                self._log(
                    f"TMDb error on '{movie_name}' (ID {tmdb_id}), "
                    f"attempt {attempt}/{attempts}: {e}"
                )
                time.sleep(1)

        self._log(f"Skipping movie '{movie_name}' after repeated TMDb failures.")
        self.cache[key] = None
        self._save_cache()
        return None

    def get_poster(self, collection_id):
        data = self.get(f"/collection/{collection_id}")
        if not data:
            return None
        poster = data.get("poster_path")
        if not poster:
            return None

        url = "https://image.tmdb.org/t/p/original" + poster
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.content
        except Exception:
            return None
