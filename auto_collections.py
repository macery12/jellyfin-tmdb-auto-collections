#!/usr/bin/env python3
import os
import sys
import time
import logging
import re
from collections import deque

import requests

# =============================
# Interactive DRY RUN prompt
# =============================

def ask_dry_run():
    while True:
        ans = input("Do you want to run a DRY RUN first? (y/n): ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Enter Y or N")

DRY_RUN = ask_dry_run()

# =============================
# Logging setup
# =============================

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger("collections")

# =============================
# Environment / Config
# =============================

JELLYFIN_URL = os.getenv("JELLYFIN_URL", "").rstrip("/")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
JELLYFIN_USER_ID = os.getenv("JELLYFIN_USER_ID", "").strip()

MIN_MOVIES = 2
LANG = "en-US"

if not JELLYFIN_URL or not JELLYFIN_API_KEY or not TMDB_API_KEY:
    log.error("Missing environment variables. Copy config.example.env → .env and edit it.")
    sys.exit(1)

# =============================
# TMDb Rate Limiter
# =============================

TMDB_MAX_CALLS = 35
TMDB_PERIOD = 10.0

class RateLimiter:
    def __init__(self, max_calls, period):
        self.max_calls, self.period = max_calls, period
        self.calls = deque()

    def wait(self):
        now = time.time()
        while self.calls and now - self.calls[0] > self.period:
            self.calls.popleft()

        if len(self.calls) >= self.max_calls:
            sleep = self.period - (now - self.calls[0]) + 0.05
            time.sleep(sleep)

        self.calls.append(time.time())

tmdb_limit = RateLimiter(TMDB_MAX_CALLS, TMDB_PERIOD)

# =============================
# Helper Functions
# =============================

INVALID = re.compile(r'[:<>\"/\\|?*]')

def sanitize(name):
    return re.sub(r"\s+", " ", INVALID.sub(" ", name)).strip()

def jf_headers():
    return {
        "X-Emby-Token": JELLYFIN_API_KEY,
        "Accept": "application/json",
    }

def jf_get(path, params=None):
    r = requests.get(f"{JELLYFIN_URL}{path}", headers=jf_headers(), params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def jf_post(path, params=None, json=None):
    if DRY_RUN:
        log.info(f"[DRY RUN] Would POST → {path}")
        return None

    r = requests.post(f"{JELLYFIN_URL}{path}", headers=jf_headers(), params=params, json=json, timeout=20)
    if r.status_code not in (200, 201, 204):
        r.raise_for_status()

    try:
        return r.json()
    except:
        return None

def jf_upload_image(item_id, image_type, image_bytes):
    if DRY_RUN:
        log.info(f"[DRY RUN] Would upload poster to → {item_id}")
        return

    r = requests.post(
        f"{JELLYFIN_URL}/Items/{item_id}/Images/{image_type}",
        headers={"X-Emby-Token": JELLYFIN_API_KEY},
        files={"file": ("poster.jpg", image_bytes, "image/jpeg")},
        timeout=30,
    )
    if r.status_code not in (200, 204):
        log.warning(f"Failed to upload poster: {r.text}")

def tmdb_get(path):
    tmdb_limit.wait()
    r = requests.get(
        f"https://api.themoviedb.org/3{path}",
        params={"api_key": TMDB_API_KEY, "language": LANG},
        timeout=20,
    )
    if r.status_code == 429:
        time.sleep(5)
        return tmdb_get(path)
    r.raise_for_status()
    return r.json()

# =============================
# Jellyfin Movie & Collection Logic
# =============================

def ensure_user_id():
    global JELLYFIN_USER_ID
    if JELLYFIN_USER_ID:
        return JELLYFIN_USER_ID

    users = jf_get("/Users")
    for u in users:
        if not u.get("IsDisabled", False):
            JELLYFIN_USER_ID = u["Id"]
            return JELLYFIN_USER_ID

    raise RuntimeError("Could not auto-detect Jellyfin user")

def jf_movies():
    user = ensure_user_id()
    movies = []
    start = 0
    size = 200

    while True:
        chunk = jf_get("/Items", {
            "IncludeItemTypes": "Movie",
            "Fields": "ProviderIds",
            "Limit": size,
            "StartIndex": start,
            "UserId": user
        }).get("Items", [])

        if not chunk:
            break
        movies += chunk
        if len(chunk) < size:
            break
        start += size

    return movies

def jf_find_collection(name: str):
    user = ensure_user_id()
    data = jf_get("/Items", {
        "IncludeItemTypes": "BoxSet",
        "SearchTerm": name,
        "UserId": user
    })
    for item in data.get("Items", []):
        if item.get("Name") == name:
            return item["Id"]
    return None

def tmdb_poster(cid):
    try:
        info = tmdb_get(f"/collection/{cid}")
        poster = info.get("poster_path")
        if not poster:
            return None
        img = requests.get("https://image.tmdb.org/t/p/original" + poster, timeout=20)
        img.raise_for_status()
        return img.content
    except:
        return None

def create_collection(name, ids):
    safe = sanitize(name)
    res = jf_post("/Collections", params={"Name": safe, "Ids": ",".join(ids)})
    if res and "Id" in res:
        return res["Id"]
    return jf_find_collection(safe)

# =============================
# Build Collection Mapping
# =============================

def build_collections(movies):
    mapping = {}
    for m in movies:
        p = m.get("ProviderIds") or {}
        tmdb_id = p.get("Tmdb") or p.get("tmdb") or p.get("TMDB")
        if not tmdb_id:
            continue

        info = tmdb_get(f"/movie/{tmdb_id}")
        col = info.get("belongs_to_collection")
        if not col:
            continue

        cid = str(col["id"])
        if cid not in mapping:
            mapping[cid] = {"name": col["name"], "ids": []}
        mapping[cid]["ids"].append(m["Id"])

    return {
        cid: data
        for cid, data in mapping.items()
        if len(data["ids"]) >= MIN_MOVIES
    }

# =============================
# Main Sync Logic
# =============================

def main():
    log.info("\n=== Jellyfin TMDb Auto Collection Builder ===\n")
    movies = jf_movies()
    cols = build_collections(movies)

    for cid, info in sorted(cols.items(), key=lambda x: x[1]["name"]):
        name = sanitize(info["name"])
        ids = info["ids"]

        existing = jf_find_collection(name)
        if existing:
            log.info(f"UPDATE → {name} ({len(ids)} movies)")
            jf_post(f"/Collections/{existing}/Items", params={"Ids": ",".join(ids)})
            collection_id = existing
        else:
            log.info(f"CREATE → {name} ({len(ids)} movies)")
            collection_id = create_collection(name, ids)

        if not collection_id:
            log.info(f"SKIP → {name} (could not create)")
            continue

        poster = tmdb_poster(cid)
        if poster:
            log.info(f"ARTWORK → Setting poster for {name}")
            jf_upload_image(collection_id, "Primary", poster)
        else:
            log.info(f"ARTWORK → No poster found for {name}")

    log.info("\n=== COMPLETE ===\n")

if __name__ == "__main__":
    main()
