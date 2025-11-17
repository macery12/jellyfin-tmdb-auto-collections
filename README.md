# Jellyfin TMDb Auto Collections

This script automatically creates movie collections in Jellyfin using TMDb’s
“belongs_to_collection” data. It detects franchises (Star Wars, Spider-Verse,
Jurassic Park, and many others), creates collections, updates existing ones, and
downloads the highest-quality primary posters from TMDb.

The tool works on Linux or Windows and requires a Jellyfin server and a TMDb API
key. It is safe to run repeatedly, and it only changes what is needed. 

---

## Features

- Detects all movies in Jellyfin, including movies already inside collections  
- Automatically creates new BoxSets based on TMDb collection data  
- Updates existing collections with missing movies  
- Downloads and sets TMDb primary posters  
- Safe TMDb rate limiting  
- Interactive dry-run mode (preview changes before applying)  
- Persistent caching to reduce API usage (`tmdb_cache.json`)  
- Clean terminal output and logs (`logs/collections.log`)  

---

## Requirements

- Python 3.9 or newer  
- A Jellyfin server  
- A TMDb API key  

---

## Installation

### 1. Clone the repository

```
git clone https://github.com/macery12/jellyfin-tmdb-auto-collections
cd jellyfin-tmdb-auto-collections
```

### 2. Install Python dependencies

Linux/macOS:

```
pip install -r requirements.txt
```

Windows:

```
py -m pip install -r requirements.txt
```

---

## Configuration (.env setup)

Create a file named `.env` in the project folder:

```
JELLYFIN_URL=http://your-jellyfin-server:8096
JELLYFIN_API_KEY=your_jellyfin_api_key
TMDB_API_KEY=your_tmdb_api_key
JELLYFIN_USER_ID=
```

### Notes

- `JELLYFIN_USER_ID` is optional — if left blank, the script automatically picks the first enabled Jellyfin user.
- The URL must include HTTP or HTTPS.

---

## Running the Script

Run the script using Python:

Linux/macOS:
```
python3 auto_collections.py
```

Windows:
```
py auto_collections.py
```

You will be prompted:

```
Dry run first? (y/n):
```

### Example dry-run interaction

```
Dry run first? (y/n): y
=== Jellyfin TMDb Auto Collection Builder ===

Found 418 movies

[1/418] Checking → Iron Man
[2/418] Checking → The Avengers
...
DRY RUN: Would POST → /Collections ...
```

You can answer “n” to apply changes and create/update collections.

---

## How It Works

1. The script fetches all Jellyfin movies, including movies already inside other collections.
2. For every movie with a TMDb ID, it queries TMDb to see if it belongs to a collection.
3. If multiple movies belong to the same TMDb collection, a Jellyfin BoxSet is created or updated.
4. The primary poster for each collection is downloaded from TMDb and uploaded to Jellyfin.
5. All TMDb responses are cached in `tmdb_cache.json` for faster subsequent runs.
6. All actions are logged to `logs/collections.log`.

---

## Artwork

The script downloads and sets **primary posters** for each created collection.

Additional artwork types (logos, backdrops, fanart) may be added in a future version or can be added manually if needed.

---

## Troubleshooting

### The script says “Missing API keys”
Check that your `.env` file exists and contains all required keys:
```
JELLYFIN_URL=
JELLYFIN_API_KEY=
TMDB_API_KEY=
```

### The script finds fewer movies than expected
Ensure this setting is present in the Jellyfin query:
```
CollapseBoxSetItems=false
```
This allows the script to see movies inside existing collections.

### TMDb errors or timeouts
The script has a retry system. If TMDb fails repeatedly for a specific movie, it skips it and continues running.

---

## Notes

- This script only creates and updates collections. It does not delete or remove movies from any existing collections.
- The script is safe to run repeatedly — it only changes what is needed.
- TMDb lookups are cached permanently until `tmdb_cache.json` is deleted.

---

## Contributing

Pull requests and suggestions are welcome.
