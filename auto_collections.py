#!/usr/bin/env python3
import os
import sys
import time
import json
import logging
import re
from collections import deque

import requests
from dotenv import load_dotenv

# ============================================================
# Load .env
# ============================================================
load_dotenv()

# ============================================================
# Colors
# ============================================================
class C:
    R = "\033[0m"
    G = "\033[92m"
    Y = "\033[93m"
    C = "\033[96m"
    R2 = "\033[91m"
    B = "\033[1m"

def col(s, c): return f"{c}{s}{C.R}"

# ============================================================
# Ask for dry run
# ============================================================
def ask_dry_run():
    while True:
        a = input("Dry run first? (y/n): ").strip().lower()
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False
        print("Enter y or n")

DRY_RUN = ask_dry_run()

# ============================================================
# Logging
# ============================================================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/collections.log",
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger("jf")

def out(msg, color=None):
    if color:
        print(col(msg, color))
        log.info(msg)
    else:
        print(msg)
        log.info(msg)

# ============================================================
# Config from env
# ============================================================
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "").rstrip("/")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
JELLYFIN_USER_ID = os.getenv("JELLYFIN_USER_ID", "").strip()

MIN_MOVIES = 2
LANG = "en-US"

if not JELLYFIN_URL or not JELLYFIN_API_KEY or not TMDB_API_KEY:
    out("Missing API keys in .env file.", C.R2)
    sys.exit(1)

# ============================================================
# TMDb rate limiter
# ============================================================
TMDB_MAX = 35
TMDB_PERIOD = 10

class RateLimiter:
    def __init__(self):
        self.calls = deque()

    def wait(self):
        now = time.time()
        while self.calls and now - self.calls[0] > TMDB_PERIOD:
            self.calls.popleft()

        if len(self.calls) >= TMDB_MAX:
            sleep = TMDB_PERIOD - (now - self.calls[0]) + 0.1
            time.sleep(sleep)

        self.calls.append(time.time())

limit = RateLimiter()

# ============================================================
# Cache load/save
# ============================================================
CACHE_FILE = "tmdb_cache.json"
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r") as f:
            TMDB_CACHE = json.load(f)
    except:
        TMDB_CACHE = {}
else:
    TMDB_CACHE = {}

def cache_save():
    with open(CACHE_FILE, "w") as f:
        json.dump(TMDB_CACHE, f, indent=2)

# ============================================================
# Jellyfin HTTP helpers
# ============================================================
INVALID = re.compile(r'[:<>\"/\\|?*]')

def clean(s):
    return re.sub(r"\s+", " ", INVALID.sub(" ", s)).strip()

def jf_headers():
    return {
        "X-Emby-Token": JELLYFIN_API_KEY,
        "Accept": "application/json"
    }

def jf_get(path, params=None):
    r = requests.get(f"{JELLYFIN_URL}{path}", headers=jf_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def jf_post(path, params=None, json=None):
    if DRY_RUN:
        out(f"[DRY RUN] POST → {path} params={params}", C.Y)
        return None

    r = requests.post(
        f"{JELLYFIN_URL}{path}",
        headers=jf_headers(),
        params=params,
        json=json,
        timeout=30
    )
    if r.status_code not in (200, 201, 204):
        r.raise_for_status()

    try:
        return r.json()
    except:
        return None

def jf_upload_image(item_id, img_type, img_bytes):
    if DRY_RUN:
        out(f"[DRY RUN] Would upload poster → {item_id}", C.Y)
        return
    r = requests.post(
        f"{JELLYFIN_URL}/Items/{item_id}/Images/{img_type}",
        headers={"X-Emby-Token": JELLYFIN_API_KEY},
        files={"file": ("poster.jpg", img_bytes, "image/jpeg")},
        timeout=30,
    )
    if r.status_code not in (200, 204):
        out(f"Poster upload failed: {r.text}", C.R2)

# ============================================================
# TMDb request with caching
# ============================================================
def tmdb_get(path, movie_name="", tmdb_id=""):
    key = path

    # Cached
    if key in TMDB_CACHE:
        return TMDB_CACHE[key]

    # Not cached → fetch
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            limit.wait()
            r = requests.get(
                f"https://api.themoviedb.org/3{path}",
                params={"api_key": TMDB_API_KEY, "language": LANG},
                timeout=5,
            )

            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "3"))
                out(f"Rate limit hit, waiting {wait}s...", C.Y)
                time.sleep(wait)
                continue

            if r.status_code == 401:
                out("TMDb API key invalid", C.R2)
                sys.exit(1)

            r.raise_for_status()
            data = r.json()

            TMDB_CACHE[key] = data
            cache_save()
            return data

        except Exception as e:
            out(
                f"TMDb ERROR on '{movie_name}' (ID {tmdb_id}), "
                f"attempt {attempt}/{attempts}: {e}",
                C.R2
            )
            time.sleep(1)

    out(f"Skipping movie '{movie_name}' after repeated failures.", C.Y)
    TMDB_CACHE[key] = None
    cache_save()
    return None

# ============================================================
# Jellyfin logic
# ============================================================
def ensure_user_id():
    global JELLYFIN_USER_ID
    if JELLYFIN_USER_ID:
        return JELLYFIN_USER_ID

    users = jf_get("/Users")
    for u in users:
        if not u.get("IsDisabled", False):
            JELLYFIN_USER_ID = u["Id"]
            return JELLYFIN_USER_ID

    raise RuntimeError("No Jellyfin user found")

def jf_movies():
    user = ensure_user_id()
    movies = []
    start = 0
    size = 200

    while True:
        d = jf_get("/Items", {
            "IncludeItemTypes": "Movie",
            "Fields": "ProviderIds",
            "CollapseBoxSetItems": "false",
            "Recursive": "true",
            "Limit": size,
            "StartIndex": start,
            "UserId": user
        })
        chunk = d.get("Items", [])
        if not chunk:
            break

        movies.extend(chunk)

        if len(chunk) < size:
            break

        start += size

    return movies

def jf_find_collection(name):
    user = ensure_user_id()
    d = jf_get("/Items", {
        "IncludeItemTypes": "BoxSet",
        "SearchTerm": name,
        "UserId": user,
        "Recursive": "true"
    })
    for item in d.get("Items", []):
        if item.get("Name") == name:
            return item["Id"]
    return None

def tmdb_poster(cid):
    data = tmdb_get(f"/collection/{cid}")
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
    except:
        return None

# ============================================================
# Build collection map
# ============================================================
def build_collections(movies):
    out("\nChecking TMDb collection info...\n", C.C)

    mapping = {}
    missing = []

    for i, m in enumerate(movies, start=1):
        name = m.get("Name", "Unknown")
        p = m.get("ProviderIds") or {}
        tmdb_id = p.get("Tmdb") or p.get("tmdb") or p.get("TMDB")

        out(f"[{i}/{len(movies)}] Checking → {name}", C.C)

        if not tmdb_id:
            missing.append(name)
            continue

        info = tmdb_get(f"/movie/{tmdb_id}", movie_name=name, tmdb_id=tmdb_id)
        if not info:
            continue

        colinfo = info.get("belongs_to_collection")
        if not colinfo:
            continue

        cid = str(colinfo["id"])
        if cid not in mapping:
            mapping[cid] = {"name": colinfo["name"], "ids": []}

        mapping[cid]["ids"].append(m["Id"])

    if missing:
        out(f"\n{len(missing)} movies missing TMDb IDs", C.Y)

    # Filter
    final = {
        cid: d for cid, d in mapping.items()
        if len(d["ids"]) >= MIN_MOVIES
    }

    return final

# ============================================================
# Main sync
# ============================================================
def main():
    out("\n=== Jellyfin TMDb Auto Collection Builder ===\n", C.C)

    movies = jf_movies()
    out(f"Found {len(movies)} movies\n", C.C)

    collections = build_collections(movies)
    out(f"\nFound {len(collections)} TMDb collections\n", C.C)

    for cid, d in sorted(collections.items(), key=lambda x: x[1]["name"]):
        name = clean(d["name"])
        ids = d["ids"]

        existing = jf_find_collection(name)
        if existing:
            out(f"ALREADY_EXISTS → {name} ({len(ids)} movies)", C.Y)
            jf_post(f"/Collections/{existing}/Items", params={"Ids": ",".join(ids)})
            cid_jf = existing
        else:
            out(f"CREATE → {name} ({len(ids)} movies)", C.G)
            cid_jf = create_collection(name, ids)

        if not cid_jf:
            out(f"Failed to create {name}", C.R2)
            continue

        poster = tmdb_poster(cid)
        if poster:
            out(f"POSTER → Applying artwork: {name}", C.C)
            jf_upload_image(cid_jf, "Primary", poster)
        else:
            out(f"POSTER → No poster found: {name}", C.Y)

    out("\n=== COMPLETE ===\n", C.G)

if __name__ == "__main__":
    main()
