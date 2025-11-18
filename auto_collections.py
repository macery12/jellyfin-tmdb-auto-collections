#!/usr/bin/env python3
import os
import sys
import time
import json
import logging
import re
from datetime import datetime

from dotenv import load_dotenv
from utils.jellyfin import Jellyfin
from utils.tmdb import TMDb
from utils.display import Display
from utils.jellyseer import JellyseerrClient

# ============================================================
# Load .env
# ============================================================
load_dotenv()

# ============================================================
# Logging setup
# ============================================================
os.makedirs("logs", exist_ok=True)
timestamp = time.strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join("logs", f"auto_collections_{timestamp}.log")

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("jf")

def out(msg):
    print(msg)
    log.info(msg)

# ============================================================
# Prompts
# ============================================================
def ask(prompt):
    while True:
        a = input(prompt).lower().strip()
        if a in ("y", "yes"): return True
        if a in ("n", "no"): return False

DRY_RUN = ask("Dry run first? (y/n): ")
OFFLINE_MODE = ask("Use offline mode? (y/n): ")

# ============================================================
# Env vars
# ============================================================
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "").rstrip("/")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
JELLYSEERR_URL = os.getenv("JELLYSEERR_URL", "").rstrip("/")
JELLYSEERR_API_KEY = os.getenv("JELLYSEERR_API_KEY")

if not JELLYFIN_URL or not JELLYFIN_API_KEY:
    out("Missing Jellyfin env vars")
    sys.exit(1)

USE_JELLYSEERR = False
if JELLYSEERR_URL and JELLYSEERR_API_KEY:
    USE_JELLYSEERR = ask("Send missing movies to Jellyseerr? (y/n): ")

# ============================================================
# Clients
# ============================================================
display = Display(logger=out)
jf = Jellyfin(JELLYFIN_URL, JELLYFIN_API_KEY, dry_run=DRY_RUN, logger=out)
tmdb = TMDb(TMDB_API_KEY, offline_mode=OFFLINE_MODE, logger=out)

JELLYSEERR_CLIENT = JellyseerrClient(JELLYSEERR_URL, JELLYSEERR_API_KEY) if USE_JELLYSEERR else None

INVALID = re.compile(r'[:<>"/\\|?*]')

def clean(s):
    return re.sub(r"\s+", " ", INVALID.sub(" ", s)).strip()

# ============================================================
# Collect Jellyfin user
# ============================================================
def ensure_user_id():
    users = jf.list_users()
    for u in users:
        if not u.get("IsDisabled"):
            return u["Id"]
    raise RuntimeError("No valid Jellyfin users found")

# ============================================================
# Offline metadata
# ============================================================
def load_offline_collections():
    path = os.path.join("metadata", "collections.json")
    if not os.path.exists(path):
        out("metadata/collections.json missing")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {str(cid): entry for cid, entry in data.get("collections", {}).items()}

# ============================================================
# Offline builder
# ============================================================
def build_collections_offline(movies, tmdb_to_jf):
    display.progress("Building collections (offline)...")
    offline = load_offline_collections()

    result = {}

    for cid, entry in offline.items():
        cname = entry.get("name", f"Collection {cid}")
        parts = entry.get("movies", [])

        matched_jf_ids = []
        all_tmdb = [m["id"] for m in parts if "id" in m]

        for m in parts:
            mid = m["id"]
            if mid in tmdb_to_jf:
                matched_jf_ids.append(tmdb_to_jf[mid])

        if len(matched_jf_ids) >= 2:
            result[cid] = {
                "name": cname,
                "ids": matched_jf_ids,
                "tmdb_collection_id": int(cid),
                "all_tmdb_ids": all_tmdb,
                "missing_tmdb_ids": [mid for mid in all_tmdb if mid not in tmdb_to_jf],
                "missing_movies": [m for m in parts if m["id"] not in tmdb_to_jf],
            }

    return result

# ============================================================
# Online builder
# ============================================================
def build_collections_online(movies, tmdb_to_jf):
    display.progress("Building collections (online)...")

    mapping = {}
    total = len(movies)

    for idx, m in enumerate(movies, start=1):
        display.tmdb_progress(idx, total)

        name = m.get("Name", "")
        p = m.get("ProviderIds") or {}
        tid = p.get("Tmdb") or p.get("tmdb") or p.get("TMDB")


        if not tid:
            continue

        info = tmdb.get(f"/movie/{tid}", movie_name=name, tmdb_id=tid)
        if not info:
            continue

        colinfo = info.get("belongs_to_collection")
        if not colinfo:
            continue

        cid = str(colinfo["id"])
        mapping.setdefault(cid, {"name": colinfo["name"], "ids": []})
        mapping[cid]["ids"].append(m["Id"])

    # Expand details
    result = {}

    for cid, d in mapping.items():
        parts = tmdb.get(f"/collection/{cid}") or {}
        parts_list = parts.get("parts", [])

        all_ids = []
        all_movies = []

        for p in parts_list:
            mid = p.get("id")
            title = p.get("title") or p.get("original_title") or ""
            if mid:
                all_ids.append(mid)
                all_movies.append({"id": mid, "title": title})

        matched = set(i for i in all_ids if i in tmdb_to_jf)

        if len(d["ids"]) >= 2:
            result[cid] = {
                "name": d["name"],
                "ids": d["ids"],
                "tmdb_collection_id": int(cid),
                "all_tmdb_ids": all_ids,
                "missing_tmdb_ids": [mid for mid in all_ids if mid not in matched],
                "missing_movies": [m for m in all_movies if m["id"] not in matched],
            }

    return result

# ============================================================
# Jellyseerr missing movies
# ============================================================
def process_missing(collections):
    if not (USE_JELLYSEERR and JELLYSEERR_CLIENT):
        return 0

    display.progress("Processing Jellyseerr requests...")

    count = 0
    current_year = datetime.now().year

    for cid, d in collections.items():
        cname = d["name"]
        for movie in d.get("missing_movies", []):
            tmdb_id = movie["id"]
            title = movie["title"]

            # --- unreleased movie guard ---
            release_year = None
            try:
                details = JELLYSEERR_CLIENT.movie_details(tmdb_id)
                # Jellyseerr may use releaseDate or release_date style
                rd = details.get("releaseDate") or details.get("release_date")
                if rd:
                    # rd is usually "YYYY-MM-DD" or "YYYY"
                    release_year = int(str(rd)[:4])
            except RuntimeError as e:
                out(f"Jellyseerr details error for {title} (TMDb {tmdb_id}): {e}")

            if release_year and release_year > current_year:
                out(
                    f"Skipping unreleased movie {title} (TMDb {tmdb_id}, "
                    f"release {release_year})"
                )
                continue
            # --- end unreleased guard ---

            if DRY_RUN:
                display.log_missing_request(title, tmdb_id, cname)
                count += 1
                continue

            # Only request if not already requested
            if not JELLYSEERR_CLIENT.is_movie_requested(tmdb_id):
                JELLYSEERR_CLIENT.request_movie(tmdb_id)
                display.log_missing_request(title, tmdb_id, cname)
                count += 1

    return count

# ============================================================
# MAIN
# ============================================================
def main():
    print("\n=== Jellyfin TMDb Auto Collection Builder ===\n")

    user_id = ensure_user_id()

    display.progress("Checking movies...")
    movies = jf.get_movies(user_id)
    total_movies = len(movies)

    # Build tmdb->jellyfin map
    tmdb_to_jf = {}
    for m in movies:
        p = m.get("ProviderIds") or {}
        tid = p.get("Tmdb") or p.get("tmdb") or p.get("TMDB")
        if tid:
            try:
                tmdb_to_jf[int(tid)] = m["Id"]
            except:
                pass

    # Build collections
    if OFFLINE_MODE:
        collections = build_collections_offline(movies, tmdb_to_jf)
    else:
        collections = build_collections_online(movies, tmdb_to_jf)

    display.progress("Processing missing movies...")
    missing_count = process_missing(collections)

    display.progress("Applying collections...")

    # Create/update collections
    for cid, d in sorted(collections.items(), key=lambda x: x[1]["name"]):
        name = clean(d["name"])
        ids = d["ids"]

        existing = jf.find_collection(name, user_id)
        if existing:
            display.log_update_collection(name, len(ids))
            jf.post(f"/Collections/{existing}/Items", params={"Ids": ",".join(ids)})
            cid_jf = existing
        else:
            display.log_create_collection(name, len(ids))
            cid_jf = jf.create_collection(name, ids)

        # Poster
        if cid_jf and not OFFLINE_MODE:
            poster = tmdb.get_poster(d["tmdb_collection_id"])
            if poster:
                jf.upload_image(cid_jf, "Primary", poster)

    # Final summary
    display.summary(
        movies_scanned=total_movies,
        collections_found=len(collections),
        missing_detected=missing_count,
        log_file_path=LOG_FILE
    )

    print("\n=== COMPLETE ===\n")


if __name__ == "__main__":
    main()
