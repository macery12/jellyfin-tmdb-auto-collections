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
from concurrent.futures import ThreadPoolExecutor, as_completed

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


def dbg(debug_enabled: bool, msg: str) -> None:
    if debug_enabled:
        logging.debug(msg)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jellyfin TMDb auto collection builder")

    parser.set_defaults(
        dry_run=True,
        jellyseer=False,
        jellyseer_send=False,
    )

    parser.add_argument(
        "--no-dryrun",
        dest="dry_run",
        action="store_false",
        help="Apply changes to Jellyfin (default is preview-only).",
    )

    parser.add_argument(
        "--jellyseer",
        dest="jellyseer",
        action="store_true",
        help="Enable Jellyseer integration in check-only mode.",
    )

    parser.add_argument(
        "--jellyseer-send",
        dest="jellyseer_send",
        action="store_true",
        help="Enable Jellyseer integration in full mode (send requests).",
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

    jobs = []
    for m in movies:
        tmdb_id = get_tmdb_id(m)
        if not tmdb_id:
            continue
        jobs.append(
            {
                "tmdb_id": tmdb_id,
                "jf_id": m["Id"],
                "name": m.get("Name", ""),
            }
        )

    total = len(jobs)
    if not total:
        return {}

    dbg(tmdb.debug, f"[COLLECT] Building collections online for {total} mapped movies")

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(
                tmdb.get,
                f"/movie/{job['tmdb_id']}",
                job["name"],
                job["tmdb_id"],
            ): job
            for job in jobs
        }

        for idx, future in enumerate(as_completed(futures), start=1):
            job = futures[future]
            display.tmdb_progress(idx, total)
            try:
                info = future.result()
            except Exception as e:
                logging.debug(f"TMDb movie fetch failed for {job['tmdb_id']}: {e}")
                continue

            if not info:
                continue

            col = info.get("belongs_to_collection")
            if not col or not col.get("id"):
                continue

            cid = str(col["id"])
            mapping.setdefault(cid, {"name": col.get("name") or "", "ids": []})
            mapping[cid]["ids"].append(job["jf_id"])

    result: Dict[str, Dict[str, Any]] = {}
    collection_ids = list(mapping.keys())
    total_collections = len(collection_ids)

    if not total_collections:
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(tmdb.get, f"/collection/{cid}"): cid for cid in collection_ids
        }

        for idx, future in enumerate(as_completed(futures), start=1):
            cid = futures[future]
            display.progress(f"Fetching collection {idx}/{total_collections} (TMDb {cid})")
            try:
                parts = future.result() or {}
            except Exception as e:
                logging.debug(f"TMDb collection fetch failed for {cid}: {e}")
                continue

            d = mapping.get(cid)
            if not d:
                continue

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

        dbg(jf.debug, f"[APPLY] Processing collection '{name}' with {len(ids)} items")

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
            dbg(jf.debug, f"[APPLY] Skipping poster upload for '{name}' (poster exists)")
            continue

        poster_bytes = tmdb.get_poster(cid)
        if not poster_bytes:
            dbg(tmdb.debug, f"[APPLY] No poster bytes for collection '{name}' (TMDb {cid})")
            continue

        jf.upload_image(jf_id, "Primary", poster_bytes)
        dbg(jf.debug, f"[APPLY] Uploaded poster for '{name}'")


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

    if not missing_ids:
        return missing_ids

    if tmdb.offline_mode or not tmdb.api_key:
        dbg(tmdb.debug, "[MISSING] Skipping TMDb prefetch (offline mode or no API key)")
        return missing_ids

    display.progress("Fetching TMDb metadata for missing movies...")

    jobs = [mid for mid in missing_ids if not cache.get_movie(mid)]
    if not jobs:
        dbg(tmdb.debug, "[MISSING] All missing movies already in cache, no TMDb prefetch needed")
        return missing_ids

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(tmdb.get, f"/movie/{mid}", "", mid): mid for mid in jobs
        }

        total_jobs = len(jobs)
        for idx, future in enumerate(as_completed(futures), start=1):
            mid = futures[future]
            display.progress(f"Missing movie TMDb fetch {idx}/{total_jobs} (TMDb {mid})")
            try:
                future.result()
                dbg(tmdb.debug, f"[MISSING] Prefetched TMDb metadata for {mid}")
            except Exception as e:
                logging.debug(f"TMDb missing movie fetch failed for {mid}: {e}")
                continue

    return missing_ids


def process_missing(
    collections: Dict[str, Dict[str, Any]],
    tmdb: TMDb,
    cache: JsonCache,
    display: Display,
    jellyseer: Optional[JellyseerrClient],
    dry_run: bool,
    dbg_enabled: bool = False,
) -> Tuple[int, Dict[str, int], int]:
    if not jellyseer:
        return 0, {}, 0

    display.progress("Processing Jellyseer requests...")
    dbg(dbg_enabled, f"[MISSING] Starting Jellyseer processing over {len(collections)} collections")
    count = 0

    skipped_stats = {
        "No metadata": 0,
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

            dbg(dbg_enabled, f"[MISSING] Evaluating TMDb {tmdb_id} ({title}) in collection '{cname}'")

            details_raw = cache.get_movie(tmdb_id)
            if details_raw:
                dbg(dbg_enabled, f"[META] Using cached metadata for TMDb {tmdb_id} ({title})")
            else:
                dbg(dbg_enabled, f"[META] No cache entry for TMDb {tmdb_id}")

            if not details_raw and tmdb.api_key and not tmdb.offline_mode:
                dbg(dbg_enabled, f"[META] Attempting TMDb API for TMDb {tmdb_id}")
                try:
                    api_data = tmdb.get(f"/movie/{tmdb_id}", movie_name=title, tmdb_id=tmdb_id)
                    if api_data:
                        details_raw = api_data
                        cache.set_movie(tmdb_id, api_data)
                        dbg(dbg_enabled, f"[META] TMDb API success for TMDb {tmdb_id}")
                except Exception as e:
                    logging.debug(f"TMDb API failed for missing movie {tmdb_id}: {e}")
                    dbg(dbg_enabled, f"[META] TMDb API FAILED for TMDb {tmdb_id}: {e}")

            if not details_raw and jellyseer:
                dbg(dbg_enabled, f"[META] Attempting Jellyseerr fallback for TMDb {tmdb_id}")
                fallback = jellyseer.fallback_tmdb_movie(tmdb_id)
                if fallback:
                    details_raw = fallback
                    cache.set_movie(tmdb_id, fallback)
                    dbg(dbg_enabled, f"[META] Jellyseerr fallback success for TMDb {tmdb_id}")
                else:
                    dbg(dbg_enabled, f"[META] Jellyseerr fallback FAILED for TMDb {tmdb_id}")

            if not details_raw:
                skipped_stats["No metadata"] += 1
                dbg(dbg_enabled, f"[SKIP] TMDb {tmdb_id} skipped due to NO METADATA")
                continue

            details = CachedMovie.from_tmdb(details_raw)
            release_date = details.release_date
            status = details.status

            if not release_date:
                skipped_stats["No release date"] += 1
                dbg(dbg_enabled, f"[SKIP] TMDb {tmdb_id} skipped: no release date")
                continue

            try:
                release_year = int(str(release_date)[:4])
            except Exception:
                skipped_stats["Invalid release date"] += 1
                dbg(dbg_enabled, f"[SKIP] TMDb {tmdb_id} skipped: invalid release date '{release_date}'")
                continue

            if release_year > CURRENT_YEAR:
                skipped_stats["Unreleased (future year)"] += 1
                dbg(dbg_enabled, f"[SKIP] TMDb {tmdb_id} skipped: unreleased (year={release_year})")
                continue

            if status in ("Rumored", "Planned"):
                skipped_stats["Rumored/Planned"] += 1
                dbg(dbg_enabled, f"[SKIP] TMDb {tmdb_id} skipped: status={status}")
                continue

            if dry_run:
                display.log_missing_request(title, tmdb_id, cname)
                dbg(dbg_enabled, f"[JELLYSEER] DRY-RUN: would request TMDb {tmdb_id} ({title})")
                count += 1
                continue

            try:
                existing = jellyseer.is_movie_requested(tmdb_id)
            except Exception as e:
                logging.debug(f"Jellyseer check failed for {tmdb_id}: {e}")
                dbg(dbg_enabled, f"[JELLYSEER] Check FAILED for TMDb {tmdb_id}: {e}")
                existing = None

            if not existing:
                try:
                    jellyseer.request_movie(tmdb_id)
                    display.log_missing_request(title, tmdb_id, cname)
                    dbg(dbg_enabled, f"[JELLYSEER] Requested TMDb {tmdb_id} ({title})")
                    count += 1
                except Exception as e:
                    logging.warning(f"Jellyseer request failed for {tmdb_id}: {e}")
                    dbg(dbg_enabled, f"[JELLYSEER] Request FAILED for TMDb {tmdb_id}: {e}")
            else:
                dbg(dbg_enabled, f"[JELLYSEER] Skipping TMDb {tmdb_id} ({title}) - already requested/present")

    dbg(dbg_enabled, f"[MISSING] Finished Jellyseer processing: total_missing={total_missing}, sent/check_only={count}, skipped={skipped_stats}")
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

    if not total:
        out("No TMDb IDs found in Jellyfin movies, nothing to cache.")
        return

    jobs = list(ids)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(tmdb.get, f"/movie/{mid}", "", mid): mid for mid in jobs
        }

        for idx, future in enumerate(as_completed(futures), start=1):
            mid = futures[future]
            display.progress(f"Rebuild TMDb movie {idx}/{total} (TMDb {mid})")
            try:
                future.result()
            except Exception as e:
                logging.debug(f"TMDb rebuild fetch failed for {mid}: {e}")
                continue

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
    has_tmdb_key = bool(tmdb_key)

    if args.rebuild_cache and not has_tmdb_key:
        out("TMDB_API_KEY is required for --rebuild-cache.")
        sys.exit(1)

    jellyseer_enabled = args.jellyseer or args.jellyseer_send

    jellyseer_client: Optional[JellyseerrClient] = None
    if jellyseer_enabled:
        js_url = os.getenv("JELLYSEERR_URL")
        js_key = os.getenv("JELLYSEERR_API_KEY")
        if not js_url or not js_key:
            out("Jellyseer flags were used but JELLYSEERR_URL or JELLYSEERR_API_KEY is missing in the environment.")
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
        offline_mode=not has_tmdb_key,
        logger=logging.info,
        debug=args.debug,
    )
    display = Display(logger=out)
    jf = Jellyfin(jf_url, jf_key, dry_run=args.dry_run, logger=out, debug=args.debug)

    user_id = pick_user_id(jf)

    mode_str = "ONLINE (TMDb API)" if has_tmdb_key else "OFFLINE (local metadata)"
    out("")
    out("=== Jellyfin TMDb Auto Collection Builder ===")
    out("")
    out(
        f"Mode: {mode_str} | "
        f"Dry run: {args.dry_run} | "
        f"Jellyseer: {bool(jellyseer_client)}"
    )
    out("")

    if args.rebuild_cache:
        rebuild_cache(jf, tmdb, cache, user_id, display)
        return

    movies = jf.get_movies(user_id)
    movies_scanned = len(movies)
    out(f"Found {movies_scanned} movies")

    tmdb_to_jf = build_tmdb_mapping(movies)

    if has_tmdb_key:
        collections = build_collections_online(movies, tmdb_to_jf, tmdb, display)
    else:
        collections = build_collections_offline(movies, tmdb_to_jf, display)

    collections_found = len(collections)
    out(f"\nFound {collections_found} collections\n")

    missing_ids: List[int] = []
    missing_total = 0
    skipped_stats: Dict[str, int] = {}

    if jellyseer_enabled and collections:
        if has_tmdb_key:
            missing_ids = batch_prefetch_missing_tmdb(collections, tmdb, cache, display)

        dry_run_for_jellyseer = not args.jellyseer_send
        missing_count, skipped_stats, total_missing = process_missing(
            collections=collections,
            tmdb=tmdb,
            cache=cache,
            display=display,
            jellyseer=jellyseer_client,
            dry_run=dry_run_for_jellyseer,
            dbg_enabled=args.debug,
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
