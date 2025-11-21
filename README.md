# Jellyfin TMDb Auto Collection Builder

Automatically creates and updates Jellyfin movie collections using real TMDb collection data.  
Supports optional Jellyseer integration for requesting missing movies.

This tool builds movie collections, keeps Jellyfin boxsets up to date, and can notify (or request through) Jellyseer when movies are missing — all while handling TMDb API usage, rate limiting, and caching safely.

---

# Installation

```bash
git clone https://github.com/macery12/jellyfin-tmdb-auto-collections
cd jellyfin-tmdb-auto-collections
pip install -r requirements.txt
```

Create a `.env` file:

```
JELLYFIN_URL=http://your-jellyfin:8096
JELLYFIN_API_KEY=xxxxxx
TMDB_API_KEY=xxxxxx       # optional, enables online mode
JELLYSEERR_URL=http://your-jellyseer:5055
JELLYSEERR_API_KEY=xxxxxx
```

If **TMDB_API_KEY** is missing, the script automatically runs in **offline mode** and uses the local metadata folder.

---

# Automatic TMDb Mode Detection

The program automatically selects between **online** and **offline** modes:

| Condition | Behavior |
|----------|-----------|
| `TMDB_API_KEY` exists | **Online Mode** – TMDb API is used to discover collections, enrich metadata, and fetch posters. |
| No TMDb key | **Offline Mode** – Uses `metadata/collections.json` and TMDb cache only. |

TMDb cache is always used when available.

---

# Command-Line Arguments

## General Behavior
| Flag | Description |
|------|-------------|
| `--no-dryrun` | Apply changes to Jellyfin. Default behavior is preview-only. |
| `--debug` | Enable verbose logging for TMDb, Jellyfin, and Jellyseer operations. |

---

## Jellyseer Integration

Jellyseer integration is optional and supports two modes:

| Flag | Description |
|------|-------------|
| `--jellyseer` | Enable Jellyseer **check-only** mode. Missing movies are detected, TMDb metadata is loaded (API or cached), and Jellyseer is checked to see if movies already exist. **No requests are sent.** |
| `--jellyseer-send` | Enable Jellyseer **full mode**. Detects missing movies, loads metadata, checks their Jellyseer status, and **sends requests** for missing titles. Automatically implies `--jellyseer`. |

### Behavior Summary

| Flags Used | Missing Detection | Jellyseer Check | Request Sending |
|------------|-------------------|------------------|------------------|
| *(none)* | No | No | No |
| `--jellyseer` | Yes | Yes (check-only) | No |
| `--jellyseer-send` | Yes | Yes | Yes |

---

# Usage Examples

### 1. Default run (offline if TMDb key missing)
```bash
python auto_collections.py
```
- Detects TMDb key automatically  
- Preview-only  
- No Jellyseer

---

### 2. Apply changes to Jellyfin
```bash
python auto_collections.py --no-dryrun
```
Updates Jellyfin collections, uploads posters, creates boxsets.

---

### 3. Enable Jellyseer (check-only mode)
```bash
python auto_collections.py --jellyseer
```
- Detect missing movies  
- Load metadata (online or cached)  
- Check Jellyseer for existing requests  
- Shows what would be requested  
- Does **not** send anything

---

### 4. Send missing movies to Jellyseer
```bash
python auto_collections.py --jellyseer-send
```
Runs Jellyseer in full operational mode.

Add `--no-dryrun` to update Jellyfin too.

---

### 5. Full pipeline: update Jellyfin + send to Jellyseer
```bash
python auto_collections.py --no-dryrun --jellyseer-send
```

---

### 6. Debug everything
```bash
python auto_collections.py --debug --jellyseer-send --no-dryrun
```

---

# Summary Output Example

```
=== SUMMARY ===
Movies scanned:                 431
Collections discovered:          21
Collections created:             18
Collections updated:              3
Missing movies detected:         29
Jellyseer requests sent:         29
Log saved to logs/auto_collections_YYYYMMDD_HHMMSS.log
```
