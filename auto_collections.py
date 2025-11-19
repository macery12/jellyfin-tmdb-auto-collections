
import os
import sys
import time
import json
import logging
import re
import argparse
from datetime import datetime

from dotenv import load_dotenv

from utils.jellyfin import Jellyfin
from utils.tmdb import TMDb
from utils.display import Display
from utils.jellyseer import JellyseerrClient

# CONSTANTS
LOG_DIR = "logs"
LOG_FILE_TEMPLATE = "auto_collections_{timestamp}.log"

MIN_MOVIES = 2
INVALID_FILENAME_CHARS = re.compile(r'[:<>"/\\|?*]')
CURRENT_YEAR = datetime.now().year

DEFAULT_DRY_RUN = True
DEFAULT_OFFLINE = True
DEFAULT_JELLYSEERR = False

# ENV + LOGGING
load_dotenv()

os.makedirs(LOG_DIR, exist_ok=True)
TIMESTAMP = time.strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, LOG_FILE_TEMPLATE.format(timestamp=TIMESTAMP))

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



# ARGPARSE
def parse_args():
    parser = argparse.ArgumentParser(description="Jellyfin TMDb Auto Collection Builder")

    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Perform checks only (default)")
    parser.add_argument("--no-dryrun", dest="dry_run", action="store_false", help="Apply changes to Jellyfin")

    parser.add_argument("--offline", dest="offline", action="store_true", help="Use metadata/collections.json")
    parser.add_argument("--online", dest="offline", action="store_false", help="Use TMDb API (default)")

    parser.add_argument("--jellyseerr", dest="jellyseerr", action="store_true", help="Send missing movies to Jellyseerr")
    parser.add_argument("--no-jellyseerr", dest="jellyseerr", action="store_false", help="Disable Jellyseerr")

    parser.set_defaults(
        dry_run=DEFAULT_DRY_RUN,
        offline=DEFAULT_OFFLINE,
        jellyseerr=DEFAULT_JELLYSEERR,
    )

    return parser.parse_args()


ARGS = parse_args()
DRY_RUN = ARGS.dry_run
OFFLINE_MODE = ARGS.offline



# ENV VARS
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "").rstrip("/")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

JELLYSEERR_URL = os.getenv("JELLYSEERR_URL", "").rstrip("/")
JELLYSEERR_API_KEY = os.getenv("JELLYSEERR_API_KEY")

if not JELLYFIN_URL or not JELLYFIN_API_KEY:
    out("Missing Jellyfin env vars")
    sys.exit(1)

if not OFFLINE_MODE and not TMDB_API_KEY:
    out("TMDB_API_KEY required in online mode")
    sys.exit(1)

USE_JELLYSEERR = (
    ARGS.jellyseerr and JELLYSEERR_URL and JELLYSEERR_API_KEY
)



# HELPERS
def clean_filename(s):
    return re.sub(r"\s+", " ", INVALID_FILENAME_CHARS.sub(" ", s)).strip()

def get_tmdb_id(item):
    """Extract TMDb ID reliably from a Jellyfin item."""
    p = item.get("ProviderIds") or {}
    tid = p.get("Tmdb") or p.get("tmdb") or p.get("TMDB")
    if not tid:
        return None
    try:
        return int(tid)
    except:
        return None

# CLIENTS
display = Display(logger=out)
jf = Jellyfin(JELLYFIN_URL, JELLYFIN_API_KEY, dry_run=DRY_RUN, logger=out)
tmdb = TMDb(TMDB_API_KEY, offline_mode=OFFLINE_MODE, logger=out)

JELLYSEERR_CLIENT = JellyseerrClient(JELLYSEERR_URL, JELLYSEERR_API_KEY) if USE_JELLYSEERR else None

# USER SELECTION
def ensure_user_id():
    users = jf.list_users()
    for u in users:
        if not u.get("IsDisabled"):
            return u["Id"]
    raise RuntimeError("No valid Jellyfin users found")

# OFFLINE METADATA
def load_offline_collections():
    path = os.path.join("metadata", "collections.json")
    if not os.path.exists(path):
        out("metadata/collections.json missing (offline mode)")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        return {str(cid): entry for cid, entry in json.load(f).get("collections", {}).items()}


# BUILD COLLECTIONS (OFFLINE)
def build_collections_offline(movies, tmdb_to_jf):
    display.progress("Building collections (offline)...")
    offline = load_offline_collections()
    results = {}

    for cid, entry in offline.items():
        cname = entry.get("name", f"Collection {cid}")
        parts = entry.get("movies", [])

        matched = []
        all_tmdb = []

        for m in parts:
            mid = m["id"]
            all_tmdb.append(mid)
            if mid in tmdb_to_jf:
                matched.append(tmdb_to_jf[mid])

        if len(matched) >= MIN_MOVIES:
            results[cid] = {
                "name": cname,
                "ids": matched,
                "tmdb_collection_id": int(cid),
                "all_tmdb_ids": all_tmdb,
                "missing_tmdb_ids": [mid for mid in all_tmdb if mid not in tmdb_to_jf],
                "missing_movies": [m for m in parts if m["id"] not in tmdb_to_jf],
            }

    return results

# BUILD COLLECTIONS (ONLINE)
def build_collections_online(movies, tmdb_to_jf):
    display.progress("Building collections (online)...")

    mapping = {}
    total = len(movies)

    for idx, m in enumerate(movies, start=1):
        display.tmdb_progress(idx, total)

        tmdb_id = get_tmdb_id(m)
        if not tmdb_id:
            continue

        info = tmdb.get(f"/movie/{tmdb_id}", movie_name=m.get("Name", ""), tmdb_id=tmdb_id)
        if not info:
            continue

        col = info.get("belongs_to_collection")
        if not col:
            continue

        cid = str(col["id"])
        mapping.setdefault(cid, {"name": col["name"], "ids": []})
        mapping[cid]["ids"].append(m["Id"])

    result = {}

    for cid, d in mapping.items():
        parts = tmdb.get(f"/collection/{cid}") or {}
        items = parts.get("parts", [])

        all_tmdb = [i.get("id") for i in items if i.get("id")]
        all_movies = [
            {"id": i.get("id"), "title": i.get("title") or i.get("original_title") or ""}
            for i in items
            if i.get("id")
        ]

        matched = set(x for x in all_tmdb if x in tmdb_to_jf)

        if len(d["ids"]) >= MIN_MOVIES:
            result[cid] = {
                "name": d["name"],
                "ids": d["ids"],
                "tmdb_collection_id": int(cid),
                "all_tmdb_ids": all_tmdb,
                "missing_tmdb_ids": [mid for mid in all_tmdb if mid not in matched],
                "missing_movies": [m for m in all_movies if m["id"] not in matched],
            }

    return result

# JELLYSEERR MISSING MOVIES
def process_missing(collections):
    if not (USE_JELLYSEERR and JELLYSEERR_CLIENT):
        return 0

    display.progress("Processing Jellyseerr requests...")
    count = 0

    for cid, d in collections.items():
        cname = d["name"]

        for movie in d["missing_movies"]:
            tmdb_id = movie["id"]
            title = movie["title"]

            release_year = None
            try:
                details = JELLYSEERR_CLIENT.movie_details(tmdb_id)
                rd = details.get("releaseDate") or details.get("release_date")
                if rd:
                    release_year = int(str(rd)[:4])
            except:
                pass

            if release_year and release_year > CURRENT_YEAR:
                out(f"Skipping unreleased movie {title} (TMDb {tmdb_id}, {release_year})")
                continue

            if DRY_RUN:
                display.log_missing_request(title, tmdb_id, cname)
                count += 1
                continue

            if not JELLYSEERR_CLIENT.is_movie_requested(tmdb_id):
                JELLYSEERR_CLIENT.request_movie(tmdb_id)
                display.log_missing_request(title, tmdb_id, cname)
                count += 1

    return count

# MAIN
def main():
    print("\n=== Jellyfin TMDb Auto Collection Builder ===")
    print(f"Mode: {'OFFLINE' if OFFLINE_MODE else 'ONLINE'} | "
          f"Dry run: {DRY_RUN} | "
          f"Jellyseerr: {USE_JELLYSEERR}\n")

    user_id = ensure_user_id()

    display.progress("Checking movies...")
    movies = jf.get_movies(user_id)
    total_movies = len(movies)

    tmdb_to_jf = {}
    for m in movies:
        tid = get_tmdb_id(m)
        if tid:
            tmdb_to_jf[tid] = m["Id"]

    collections = (
        build_collections_offline(movies, tmdb_to_jf)
        if OFFLINE_MODE
        else build_collections_online(movies, tmdb_to_jf)
    )

    display.progress("Processing missing movies...")
    missing_count = process_missing(collections)

    display.progress("Applying collections...")

    for cid, d in sorted(collections.items(), key=lambda x: x[1]["name"]):
        name = clean_filename(d["name"])
        ids = d["ids"]

        existing = jf.find_collection(name, user_id)
        if existing:
            display.log_update_collection(name, len(ids))
            jf.post(f"/Collections/{existing}/Items", params={"Ids": ",".join(ids)})
            cid_jf = existing
        else:
            display.log_create_collection(name, len(ids))
            cid_jf = jf.create_collection(name, ids)

        if cid_jf and not OFFLINE_MODE:
            poster = tmdb.get_poster(d["tmdb_collection_id"])
            if poster:
                jf.upload_image(cid_jf, "Primary", poster)

    display.summary(
        movies_scanned=total_movies,
        collections_found=len(collections),
        missing_detected=missing_count,
        log_file_path=LOG_FILE,
    )

    print("\n=== COMPLETE ===\n")


if __name__ == "__main__":
    main()
