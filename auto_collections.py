#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from utils.cache import JsonCache
from utils.display import Display
from utils.jellyfin import Jellyfin
from utils.jellyseer import JellyseerrClient
from utils.tmdb import TMDb

CURRENT_YEAR = time.localtime().tm_year
MIN_MOVIES = 2
LOG_DIR = Path("logs")
CACHE_FILE = Path("tmdb_cache.json")
METADATA_DIR = Path("metadata")


@dataclass
class CachedMovie:
    id: int
    title: str
    release_date: Optional[str]
    status: Optional[str]

    @classmethod
    def from_tmdb(cls, data: Dict[str, Any]) -> "CachedMovie":
        return cls(
            id=int(data.get("id") or 0),
            title=(data.get("title") or "")[:256],
            release_date=data.get("release_date"),
            status=data.get("status"),
        )


def setup_logging(debug: bool) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"auto_collections_{ts}.log"

    logging.basicConfig(
        filename=str(log_file),
        filemode="a",
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.DEBUG if debug else logging.INFO,
    )
    return log_file


def out(msg: str) -> None:
    print(msg)
    logging.info(msg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jellyfin TMDb auto collection builder")

    parser.set_defaults(
        dry_run=True,
        offline=False,
        use_jellyseerr=False,
        skip_missing=False,
    )

    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview changes only (default).",
    )
    parser.add_argument(
        "--no-dryrun",
        dest="dry_run",
        action="store_false",
        help="Apply changes to Jellyfin.",
    )

    parser.add_argument(
        "--offline",
        dest="offline",
        action="store_true",
        help="Use metadata/collections.json instead of TMDb.",
    )
    parser.add_argument(
        "--online",
        dest="offline",
        action="store_false",
        help="Use TMDb API (default).",
    )

    parser.add_argument(
        "--jellyseerr",
        dest="use_jellyseerr",
        action="store_true",
        help="Enable Jellyseerr integration.",
    )
    parser.add_argument(
        "--no-jellyseerr",
        dest="use_jellyseerr",
        action="store_false",
        help="Disable Jellyseerr integration.",
    )

    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        help="Enable debug logging.",
    )

    parser.add_argument(
        "--rebuild-cache",
        dest="rebuild_cache",
        action="store_true",
        help="Rebuild TMDb cache and exit.",
    )

    parser.add_argument(
        "--skip-missing",
        dest="skip_missing",
        action="store_true",
        help="Skip processing missing movies and Jellyseerr requests.",
    )

    return parser.parse_args()


def get_env_or_die(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing required environment variable: {name}")
        sys.exit(1)
    return value


def get_tmdb_id(item: Dict[str, Any]) -> Optional[int]:
    provider_ids = item.get("ProviderIds") or {}
    tmdb_raw = provider_ids.get("Tmdb") or provider_ids.get("tmdb")
    if not tmdb_raw:
        return None
    try:
        return int(tmdb_raw)
    except Exception:
        return None


def load_offline_collections() -> Dict[str, Dict[str, Any]]:
    path = METADATA_DIR / "collections.json"
    if not path.exists():
        out("ERROR: metadata/collections.json not found (required in offline mode).")
        sys.exit(1)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    cols = data.get("collections", {})
    result: Dict[str, Dict[str, Any]] = {}
    for cid, entry in cols.items():
        name = entry.get("name") or f"Collection {cid}"
        movies = entry.get("movies", [])
        result[str(cid)] = {
            "name": name,
            "movies": [
                {"id": int(m.get("id")), "title": m.get("title") or ""}
                for m in movies
                if m.get("id")
            ],
        }
    return result


def build_tmdb_mapping(movies: List[Dict[str, Any]]) -> Dict[int, List[str]]:
    mapping: Dict[int, List[str]] = {}
    for m in movies:
        tmdb_id = get_tmdb_id(m)
        if not tmdb_id:
            continue
        mapping.setdefault(tmdb_id, []).append(m["Id"])
    return mapping


def build_collections_offline(
    movies: List[Dict[str, Any]],
    tmdb_to_jf: Dict[int, List[str]],
    display: Display,
) -> Dict[str, Dict[str, Any]]:
    display.progress("Building collections (offline)...")
    collections_meta = load_offline_collections()
    result: Dict[str, Dict[str, Any]] = {}

    for cid, entry in collections_meta.items():
        name = entry["name"]
        all_movies = entry["movies"]
        all_tmdb_ids = [m["id"] for m in all_movies]
        matched_ids: List[str] = []
        missing_movies: List[Dict[str, Any]] = []

        for m in all_movies:
            mid = m["id"]
            if mid in tmdb_to_jf:
                matched_ids.extend(tmdb_to_jf[mid])
            else:
                missing_movies.append(m)

        if len(matched_ids) >= MIN_MOVIES:
            result[cid] = {
                "name": name,
                "ids": matched_ids,
                "tmdb_collection_id": int(cid),
                "all_tmdb_ids": all_tmdb_ids,
                "missing_tmdb_ids": [m["id"] for m in missing_movies],
                "missing_movies": missing_movies,
            }

    return result


def build_collections_online(
    movies: List[Dict[str, Any]],
    tmdb_to_jf: Dict[int, List[str]],
    tmdb: TMDb,
    display: Display,
) -> Dict[str, Dict[str, Any]]:
    display.progress("Building collections (online)...")

    mapping: Dict[str, Dict[str, Any]] = {}
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
        if not col or not col.get("id"):
            continue

        cid = str(col["id"])
        mapping.setdefault(cid, {"name": col.get("name") or "", "ids": []})
        mapping[cid]["ids"].append(m["Id"])

    result: Dict[str, Dict[str, Any]] = {}
    total_collections = len(mapping)

    for idx, (cid, d) in enumerate(mapping.items(), start=1):
        display.progress(f"Fetching collection {idx}/{total_collections} (TMDb {cid})")

        parts = tmdb.get(f"/collection/{cid}") or {}
        items = parts.get("parts", [])

        all_tmdb = [i.get("id") for i in items if i.get("id")]
        all_movies = [
            {"id": i.get("id"), "title": i.get("title") or i.get("original_title") or ""}
            for i in items
            if i.get("id")
        ]

        matched = {mid for mid in all_tmdb if mid in tmdb_to_jf}

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


def apply_collections(
    jf: Jellyfin,
    tmdb: TMDb,
    display: Display,
    collections: Dict[str, Dict[str, Any]],
    user_id: str,
    dry_run: bool,
    skip_poster_if_exists: bool = True,
) -> None:
    for cid, data in collections.items():
        name = data["name"]
        ids = data["ids"]

        existing_id = jf.find_collection(name, user_id)

        if existing_id:
            jf.post(f"/Collections/{existing_id}/Items", params={"Ids": ",".join(ids)})
            display.log_update_collection(name, len(ids))
            jf_id = existing_id
        else:
            jf_id = jf.create_collection(name, ids)
            if jf_id:
                display.log_create_collection(name, len(ids))

        if not jf_id:
            continue

        if skip_poster_if_exists and jf.has_primary_image(jf_id):
            continue

        poster_bytes = tmdb.get_poster(cid)
        if not poster_bytes:
            continue

        jf.upload_image(jf_id, "Primary", poster_bytes)


def batch_prefetch_missing_tmdb(
    collections: Dict[str, Dict[str, Any]],
    tmdb: TMDb,
    cache: JsonCache,
    display: Display,
) -> List[int]:
    missing_ids: List[int] = []
    for d in collections.values():
        for m in d["missing_movies"]:
            mid = m["id"]
            if mid not in missing_ids:
                missing_ids.append(mid)

    total = len(missing_ids)
    if not total:
        return missing_ids

    display.progress("Fetching TMDb metadata for missing movies...")
    for idx, mid in enumerate(missing_ids, start=1):
        if cache.has_movie(mid):
            continue
        display.progress(f"Missing movie TMDb fetch {idx}/{total} (TMDb {mid})")
        tmdb.get(f"/movie/{mid}", movie_name="", tmdb_id=mid)

    return missing_ids


def process_missing(
    collections: Dict[str, Dict[str, Any]],
    tmdb: TMDb,
    cache: JsonCache,
    display: Display,
    jellyseer: Optional[JellyseerrClient],
    dry_run: bool,
) -> Tuple[int, Dict[str, int], int]:
    if not jellyseer:
        return 0, {}, 0

    display.progress("Processing Jellyseerr requests...")
    count = 0

    skipped_stats = {
        "No TMDb details": 0,
        "No release date": 0,
        "Invalid release date": 0,
        "Unreleased (future year)": 0,
        "Rumored/Planned": 0,
    }

    total_missing = 0

    for cid, d in collections.items():
        cname = d["name"]

        for movie in d["missing_movies"]:
            tmdb_id = movie["id"]
            title = movie["title"]
            total_missing += 1

            details_raw = cache.get_movie(tmdb_id)
            if not details_raw:
                skipped_stats["No TMDb details"] += 1
                continue

            details = CachedMovie.from_tmdb(details_raw)
            release_date = details.release_date
            status = details.status

            if not release_date:
                skipped_stats["No release date"] += 1
                continue

            try:
                release_year = int(str(release_date)[:4])
            except Exception:
                skipped_stats["Invalid release date"] += 1
                continue

            if release_year > CURRENT_YEAR:
                skipped_stats["Unreleased (future year)"] += 1
                continue

            if status in ("Rumored", "Planned"):
                skipped_stats["Rumored/Planned"] += 1
                continue

            if dry_run:
                display.log_missing_request(title, tmdb_id, cname)
                count += 1
                continue

            try:
                existing = jellyseer.is_movie_requested(tmdb_id)
            except Exception as e:
                logging.debug(f"Jellyseerr check failed for {tmdb_id}: {e}")
                existing = None

            if not existing:
                try:
                    jellyseer.request_movie(tmdb_id)
                    display.log_missing_request(title, tmdb_id, cname)
                    count += 1
                except Exception as e:
                    logging.warning(f"Jellyseerr request failed for {tmdb_id}: {e}")

    return count, skipped_stats, total_missing


def rebuild_cache(
    jf: Jellyfin,
    tmdb: TMDb,
    cache: JsonCache,
    user_id: str,
    display: Display,
) -> None:
    movies = jf.get_movies(user_id)
    out(f"Rebuilding TMDb cache from {len(movies)} movies...")
    tmdb_map = build_tmdb_mapping(movies)
    ids = sorted(tmdb_map.keys())
    total = len(ids)

    for idx, mid in enumerate(ids, start=1):
        display.progress(f"Rebuild TMDb movie {idx}/{total} (TMDb {mid})")
        tmdb.get(f"/movie/{mid}", movie_name="", tmdb_id=mid)

    out("TMDb cache rebuild complete.")


def pick_user_id(jf: Jellyfin) -> str:
    user_id = os.getenv("JELLYFIN_USER_ID")
    if user_id:
        return user_id

    users = jf.list_users()
    if not users:
        out("No Jellyfin users found.")
        sys.exit(1)

    return users[0]["Id"]


def main() -> None:
    load_dotenv()
    args = parse_args()
    log_file = setup_logging(args.debug)

    jf_url = get_env_or_die("JELLYFIN_URL")
    jf_key = get_env_or_die("JELLYFIN_API_KEY")

    tmdb_key = os.getenv("TMDB_API_KEY")

    tmdb_required = not args.offline or args.rebuild_cache
    if tmdb_required and not tmdb_key:
        out("TMDB_API_KEY is required for online TMDb usage (collections or cache rebuild).")
        sys.exit(1)

    jellyseer_client: Optional[JellyseerrClient] = None
    if args.use_jellyseerr and not args.skip_missing:
        js_url = os.getenv("JELLYSEERR_URL")
        js_key = os.getenv("JELLYSEERR_API_KEY")
        if not js_url or not js_key:
            out("You passed --jellyseerr but JELLYSEERR_URL or JELLYSEERR_API_KEY is missing in the environment.")
            sys.exit(1)
        jellyseer_client = JellyseerrClient(
            base_url=js_url.rstrip("/") + "/api/v1",
            api_key=js_key,
            logger=logging.info,
            debug=args.debug,
        )

    cache = JsonCache(CACHE_FILE)
    tmdb = TMDb(
        api_key=tmdb_key or "",
        cache=cache,
        offline_mode=args.offline,
        logger=logging.info,
        debug=args.debug,
    )
    display = Display(logger=out)
    jf = Jellyfin(jf_url, jf_key, dry_run=args.dry_run, logger=out, debug=args.debug)

    user_id = pick_user_id(jf)

    out("")
    out("=== Jellyfin TMDb Auto Collection Builder ===")
    out("")
    out(
        f"Mode: {'OFFLINE' if args.offline else 'ONLINE'} | "
        f"Dry run: {args.dry_run} | "
        f"Jellyseerr: {bool(jellyseer_client and not args.skip_missing)} | "
        f"Skip missing: {args.skip_missing}"
    )
    out("")

    if args.rebuild_cache:
        if args.offline:
            out("--rebuild-cache requires online mode.")
            sys.exit(1)
        rebuild_cache(jf, tmdb, cache, user_id, display)
        return

    movies = jf.get_movies(user_id)
    movies_scanned = len(movies)
    out(f"Found {movies_scanned} movies")

    tmdb_to_jf = build_tmdb_mapping(movies)

    if args.offline:
        collections = build_collections_offline(movies, tmdb_to_jf, display)
    else:
        collections = build_collections_online(movies, tmdb_to_jf, tmdb, display)

    collections_found = len(collections)
    out(f"\nFound {collections_found} collections\n")

    missing_total = sum(len(d["missing_movies"]) for d in collections.values())

    if args.skip_missing:
        out("Skipping missing movie processing (--skip-missing).")
        missing_ids: List[int] = []
        skipped_stats: Dict[str, int] = {}
    else:
        missing_ids = batch_prefetch_missing_tmdb(collections, tmdb, cache, display)
        missing_count, skipped_stats, total_missing = process_missing(
            collections=collections,
            tmdb=tmdb,
            cache=cache,
            display=display,
            jellyseer=jellyseer_client,
            dry_run=args.dry_run,
        )
        missing_total = total_missing

    apply_collections(
        jf=jf,
        tmdb=tmdb,
        display=display,
        collections=collections,
        user_id=user_id,
        dry_run=args.dry_run,
    )

    valid_movie_ids = set(tmdb_to_jf.keys()) | set(missing_ids)
    cache.prune_movies(valid_movie_ids)

    display.summary(
        movies_scanned=movies_scanned,
        collections_found=collections_found,
        missing_detected=missing_total,
        log_file_path=str(log_file),
        skipped_stats=skipped_stats,
    )

    out("\n=== COMPLETE ===\n")


if __name__ == "__main__":
    main()
