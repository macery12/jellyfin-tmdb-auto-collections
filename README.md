# Jellyfin TMDb Auto Collection Builder

A utility that automatically builds accurate movie collections in Jellyfin using TMDb collection data.
Supports two modes:

- **Online Mode** – Uses the TMDb API for live collection data and poster downloads.
- **Offline Mode** – Uses a single metadata package (no API keys or internet required).

---

## TL;DR

- **Purpose:** Match your Jellyfin movie library to real TMDb collections and create/update collections automatically.
- **Modes:** Online (most accurate) or Offline (fast, no API needed).
- **Safety:** Fully supports dry-run to preview all changes.

---

## Features

- **Online Mode**
  - Uses TMDb API to pull full, up-to-date collection membership.
  - Downloads official TMDb collection posters.
  - Best accuracy for newly released titles or newly created TMDb collections.

- **Offline Mode**
  - Uses a prebuilt metadata pack located in `metadata/`.
  - Requires no API key and no internet access.
  - Ideal for containers, air-gapped servers, and extremely fast rescans.

- **Dry-Run Support**
  - Shows exactly what would change without modifying Jellyfin.

- **Robust Implementation**
  - Rate-limited TMDb calls (online mode).
  - Clean Jellyfin API integration.
  - Filename sanitization.
  - Detailed per-run logs stored in `logs/`.

---

## Installation

Clone the repository:

```bash
git clone https://github.com/macery12/jellyfin-tmdb-auto-collections
cd jellyfin-tmdb-auto-collections
```

Install requirements:

```bash
pip install -r requirements.txt
```

---

## Configuration

Create a `.env` file in the project directory:

```
JELLYFIN_URL=http://yourserver:8096
JELLYFIN_API_KEY=YOUR_JELLYFIN_KEY
TMDB_API_KEY=YOUR_TMDB_KEY   # Optional – only needed for online mode
JELLYFIN_USER_ID=YOUR_USERID # Optional – autodetected if omitted
```

---

## Usage

Run:

```bash
python auto_collections.py
```

You will be prompted for:

- Dry-run mode
- Offline or online mode

Examples:

```
Dry run first? (y/n): y
Use offline mode (no TMDb calls)? (y/n): y
```

---

## Offline Mode

Offline mode uses local metadata only:

```
metadata/
  collections.json
  movies.json
```

### collections.json
A full TMDb collection list, expanded and ready for Jellyfin.

### movies.json
An NDJSON TMDb movie dump:

```
{"id": 11, "original_title": "Star Wars", "popularity": 50.0}
```

### Benefits

- No API keys  
- No network delays  
- No rate limits  
- Stable and repeatable results  
- Suitable for offline servers and containers

*Poster downloads are disabled in offline mode.*

---

## Online Mode

Uses TMDb API to:

- Resolve each movie by TMDb ID  
- Detect actual TMDb collection membership  
- Pull full collection membership from TMDb  
- Download and apply posters  

Use this mode if you want the most complete and up-to-date collection data.

---

## Dry-Run

Dry-run mode performs a complete pass but does **not** create or modify anything in Jellyfin.
Useful for checking match accuracy and reviewing the run before applying changes.

---

## Logs

All runs create a timestamped log:

```
logs/auto_collections_YYYYMMDD_HHMMSS.log
```

Includes:

- Every movie scanned  
- TMDb IDs  
- Collection matches  
- Collections created or updated  
- Poster activity (online mode)  
- Errors and skipped items  

---

## Summary Output (Example)

```
=== SUMMARY ===
Mode: OFFLINE (metadata)
Total Jellyfin movies scanned: 418
Movies with TMDb IDs: 402
Movies in at least one collection: 265
Movies with TMDb IDs but no collection: 137
Collections created: 22
Collections updated: 14
Total collections processed: 36
Log file saved to: logs/auto_collections_20250117_214522.log
```

---


## Troubleshooting

- **Missing TMDb IDs:** Some Jellyfin items may not have TMDb provider IDs. Add them manually or rescan metadata.
- **Poster missing (online mode):** Check network/TMDB API key.
- **429 rate limits (online mode):** The script includes a rate limiter; offline mode avoids this entirely.

---

