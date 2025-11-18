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


def col(s, c):
    return f"{c}{s}{C.R}"


# ============================================================
# Ask for dry run / offline mode
# ============================================================
def ask_dry_run():
    while True:
        a = input("Dry run first? (y/n): ").strip().lower()
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False
        print("Enter y or n")


def ask_offline_mode():
    while True:
        a = input("Use offline mode (no TMDb calls, use metadata/*.json)? (y/n): ").strip().lower()
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False
        print("Enter y or n")


DRY_RUN = ask_dry_run()
OFFLINE_MODE = ask_offline_mode()

# ============================================================
# Logging
# ============================================================
os.makedirs("logs", exist_ok=True)
TIMESTAMP = time.strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join("logs", f"auto_collections_{TIMESTAMP}.log")

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("jf")


def out(msg, color=None):
    if color:
        print(col(msg, color))
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

if not JELLYFIN_URL or not JELLYFIN_API_KEY:
    out("Missing JELLYFIN_URL or JELLYFIN_API_KEY in .env file.", C.R2)
    sys.exit(1)

if not OFFLINE_MODE and not TMDB_API_KEY:
    out("TMDB_API_KEY is required in online mode.", C.R2)
    sys.exit(1)

# ============================================================
# Stats for summary
# ============================================================
STATS = {
    "total_movies": 0,
    "movies_with_tmdb_id": 0,
    "movies_in_collections": set(),  # Jellyfin item IDs
    "collections_created": 0,
    "collections_updated": 0,
}

# ============================================================
# TMDb rate limiter
# ============================================================
TMDB_MAX = 35
TMDB_PERIOD = 10  # seconds


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
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            TMDB_CACHE = json.load(f)
    except Exception:
        TMDB_CACHE = {}
else:
    TMDB_CACHE = {}


def cache_save():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(TMDB_CACHE, f, indent=2)


# ============================================================
# Jellyfin HTTP helpers
# ============================================================
INVALID = re.compile(r'[:<>"/\\|?*]')


def clean(s):
    return re.sub(r"\s+", " ", INVALID.sub(" ", s)).strip()


def jf_headers():
    return {
        "X-Emby-Token": JELLYFIN_API_KEY,
        "Accept": "application/json",
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
        timeout=30,
    )
    if r.status_code not in (200, 201, 204):
        r.raise_for_status()

    try:
        return r.json()
    except Exception:
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
    if OFFLINE_MODE:
        # Should never be called in offline mode if we wired everything correctly
        out("tmdb_get() called in OFFLINE_MODE; skipping.", C.Y)
        return None

    key = f"{path}"
    if key in TMDB_CACHE:
        return TMDB_CACHE[key]

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
                C.R2,
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
        d = jf_get(
            "/Items",
            {
                "IncludeItemTypes": "Movie",
                "Fields": "ProviderIds",
                "CollapseBoxSetItems": "false",
                "Recursive": "true",
                "Limit": size,
                "StartIndex": start,
                "UserId": user,
            },
        )
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
    d = jf_get(
        "/Items",
        {
            "IncludeItemTypes": "BoxSet",
            "SearchTerm": name,
            "UserId": user,
            "Recursive": "true",
        },
    )
    for item in d.get("Items", []):
        if item.get("Name") == name:
            return item["Id"]
    return None


def create_collection(name, ids):
    if not ids:
        return None

    if DRY_RUN:
        out(f"[DRY RUN] Would create collection '{name}' with {len(ids)} movies", C.Y)
        # Fake ID so later poster logic doesn't treat it as failure
        return f"DRY_RUN_{name}"

    params = {"Name": name, "Ids": ",".join(ids)}
    resp = jf_post("/Collections", params=params)
    if not resp:
        return None

    cid = resp.get("Id") or resp.get("id")
    return cid


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
    except Exception:
        return None


# ============================================================
# Offline metadata loaders (collections.json + movies.json)
# ============================================================
def load_offline_collections():
    path = os.path.join("metadata", "collections.json")
    if not os.path.exists(path):
        out("ERROR: metadata/collections.json not found (required in offline mode).", C.R2)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cols = data.get("collections", {})
    # Normalize for easier usage
    result = {}
    for cid, entry in cols.items():
        name = entry.get("name") or f"Collection {cid}"
        movies = entry.get("movies", [])
        # movies are expected as [{"id": tmdb_id, "title": "..."}]
        result[str(cid)] = {
            "name": name,
            "movies": movies,
        }
    return result


def load_offline_movies_map():
    """
    Parse metadata/movies.json which is newline-delimited JSON (NDJSON),
    like:
      {"id":3924,"original_title":"Blondie","popularity":1.19}
      {"id":6124,"original_title":"Der Mann ohne Namen","popularity":1.16}

    Returns:
        { movie_id_int : title_str }
    """

    path = os.path.join("metadata", "movies.json")
    if not os.path.exists(path):
        out("WARNING: metadata/movies.json not found; offline titles unavailable.", C.Y)
        return {}

    movies = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            mid = obj.get("id")
            if mid is None:
                continue

            # Pick best title available
            title = (
                obj.get("title")
                or obj.get("original_title")
                or ""
            ).strip()

            if title:
                movies[int(mid)] = title

    return movies


# ============================================================
# Build collection map (ONLINE mode, TMDb metadata)
# ============================================================
def build_collections_online(movies):
    out("\nChecking TMDb collection info (online mode)...\n", C.C)

    mapping = {}
    missing_tmdb = 0

    for i, m in enumerate(movies, start=1):
        name = m.get("Name", "Unknown")
        p = m.get("ProviderIds") or {}
        tmdb_id = p.get("Tmdb") or p.get("tmdb") or p.get("TMDB")

        out(f"[{i}/{len(movies)}] Checking → {name}", C.C)

        if not tmdb_id:
            missing_tmdb += 1
            continue

        STATS["movies_with_tmdb_id"] += 1

        info = tmdb_get(f"/movie/{tmdb_id}", movie_name=name, tmdb_id=tmdb_id)
        if not info:
            continue

        colinfo = info.get("belongs_to_collection")
        if not colinfo:
            # Has TMDb ID but no collection
            continue

        cid = str(colinfo["id"])
        if cid not in mapping:
            mapping[cid] = {"name": colinfo["name"], "ids": []}

        jf_id = m.get("Id")
        if jf_id:
            mapping[cid]["ids"].append(jf_id)
            STATS["movies_in_collections"].add(jf_id)

    if missing_tmdb:
        out(f"\n{missing_tmdb} movies missing TMDb IDs", C.Y)

    # Filter collections that don't meet MIN_MOVIES
    final = {
        cid: d for cid, d in mapping.items()
        if len(d["ids"]) >= MIN_MOVIES
    }

    return final


# ============================================================
# Build collection map (OFFLINE mode, metadata/*.json)
# ============================================================
def build_collections_offline(movies):
    out("\nBuilding collections from offline metadata (no TMDb)...\n", C.C)

    offline_cols = load_offline_collections()
    offline_movies_map = load_offline_movies_map()

    # Map TMDb movie id → Jellyfin item id
    tmdb_to_jf = {}

    for m in movies:
        p = m.get("ProviderIds") or {}
        tmdb_id = p.get("Tmdb") or p.get("tmdb") or p.get("TMDB")
        if not tmdb_id:
            continue
        try:
            mid = int(tmdb_id)
        except Exception:
            continue
        tmdb_to_jf[mid] = m.get("Id")
        STATS["movies_with_tmdb_id"] += 1

    collections_result = {}

    for cid, entry in offline_cols.items():
        cname = entry["name"]
        parts = entry.get("movies", [])
        matched_ids = []

        for p in parts:
            mid = p.get("id")
            if mid is None:
                continue
            jf_id = tmdb_to_jf.get(mid)
            if jf_id:
                matched_ids.append(jf_id)
                STATS["movies_in_collections"].add(jf_id)

        if len(matched_ids) >= MIN_MOVIES:
            collections_result[cid] = {
                "name": cname,
                "ids": matched_ids,
            }
            out(f"Offline collection matched: {cname} ({len(matched_ids)} movies)", C.C)

    return collections_result


# ============================================================
# Summary
# ============================================================
def print_summary(total_collections):
    total_movies = STATS["total_movies"]
    with_tmdb = STATS["movies_with_tmdb_id"]
    in_collections = len(STATS["movies_in_collections"])
    no_collection = max(0, with_tmdb - in_collections)

    out("\n=== SUMMARY ===", C.B)
    out(f"Mode: {'OFFLINE (metadata)' if OFFLINE_MODE else 'ONLINE (TMDb)'}", C.C)
    out(f"Total Jellyfin movies scanned: {total_movies}", C.C)
    out(f"Movies with TMDb IDs: {with_tmdb}", C.C)
    out(f"Movies that belong to at least one collection: {in_collections}", C.C)
    out(f"Movies with TMDb IDs but no collection: {no_collection}", C.C)
    out(f"Collections created: {STATS['collections_created']}", C.C)
    out(f"Collections updated: {STATS['collections_updated']}", C.C)
    out(f"Total TMDb collections processed: {total_collections}", C.C)
    out(f"Detailed log saved to: {LOG_FILE}", C.Y)


# ============================================================
# Main sync
# ============================================================
def main():
    out("\n=== Jellyfin TMDb Auto Collection Builder ===\n", C.C)
    out(f"Mode: {'OFFLINE' if OFFLINE_MODE else 'ONLINE'} | Dry run: {DRY_RUN}", C.C)

    movies = jf_movies()
    STATS["total_movies"] = len(movies)
    out(f"Found {len(movies)} movies\n", C.C)

    if OFFLINE_MODE:
        collections = build_collections_offline(movies)
    else:
        collections = build_collections_online(movies)

    out(f"\nFound {len(collections)} collections to apply\n", C.C)

    # Apply to Jellyfin
    for cid, d in sorted(collections.items(), key=lambda x: x[1]["name"]):
        name = clean(d["name"])
        ids = d["ids"]

        existing = jf_find_collection(name)
        if existing:
            out(f"ALREADY_EXISTS → {name} ({len(ids)} movies)", C.Y)
            if DRY_RUN:
                out(f"[DRY RUN] Would add {len(ids)} movies to existing collection '{name}'", C.Y)
            else:
                jf_post(f"/Collections/{existing}/Items", params={"Ids": ",".join(ids)})
            cid_jf = existing
            STATS["collections_updated"] += 1
        else:
            out(f"CREATE → {name} ({len(ids)} movies)", C.G)
            cid_jf = create_collection(name, ids)
            if cid_jf:
                STATS["collections_created"] += 1

        if not cid_jf:
            out(f"Failed to create {name}", C.R2)
            continue

        # Posters only in ONLINE mode
        if not OFFLINE_MODE:
            poster = tmdb_poster(cid)
            if poster:
                out(f"POSTER → Applying artwork: {name}", C.C)
                jf_upload_image(cid_jf, "Primary", poster)
            else:
                out(f"POSTER → No poster found: {name}", C.Y)

    print_summary(len(collections))
    out("\n=== COMPLETE ===\n", C.G)


if __name__ == "__main__":
    main()
