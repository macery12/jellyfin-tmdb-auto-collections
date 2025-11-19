# Jellyfin TMDb Auto Collection Builder

Automatically creates and updates movie collections in Jellyfin using real TMDb collection data.

This tool:
- Detects movie collections using TMDb
- Creates or updates Jellyfin boxsets
- Downloads posters for collections (online mode)
- Supports offline mode using local metadata
- Optionally sends missing movies to Jellyseerr

## Installation

```bash
git clone https://github.com/macery12/jellyfin-tmdb-auto-collections
cd jellyfin-tmdb-auto-collections
pip install -r requirements.txt
```

Create a `.env` file:

```
JELLYFIN_URL=http://your_jellyfin:8096
JELLYFIN_API_KEY=YOUR_JF_KEY
TMDB_API_KEY=YOUR_TMDB_KEY
JELLYSEERR_URL=http://your_jellyseerr:5055
JELLYSEERR_API_KEY=YOUR_JS_KEY
```

TMDB_API_KEY is required for **online** mode.
Jellyseerr values are optional and only used if enabled via CLI.

## Usage

### Default (dry-run)
```bash
python auto_collections.py
```

### Apply changes
```bash
python auto_collections.py --no-dryrun
```

### Online mode (TMDb)
```bash
python auto_collections.py --online
```

### Offline mode
```bash
python auto_collections.py --offline
```

### Enable Jellyseerr
```bash
python auto_collections.py --jellyseerr
```

### Example: real run + TMDb + Jellyseerr
```bash
python auto_collections.py --no-dryrun --online --jellyseerr
```

## Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Default. Preview changes only. |
| `--no-dryrun` | Apply changes to Jellyfin. |
| `--offline` | Use metadata/collections.json instead of TMDb. |
| `--online` | Use TMDb API (default). |
| `--jellyseerr` | Enable Jellyseerr requests. |
| `--no-jellyseerr` | Disable Jellyseerr integration. |

## Logs

Runs generate log files in:
```
logs/auto_collections_YYYYMMDD_HHMMSS.log
```

## Summary Example

```
=== SUMMARY ===
Movies scanned:                 431
Collections discovered:          21
Collections created:             18
Collections updated:              3
Missing movies detected:         29
Jellyseerr requests sent:        29
```

