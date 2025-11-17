# Jellyfin TMDb Auto Collections
Automatically create **movie collections** in Jellyfin using TMDb’s “belongs_to_collection” data.  
Also downloads and applies **TMDb posters** to each generated collection.

This is a standalone Python script that can be run from the command line.

---

## Features

- Detects all movies that contain a TMDb ID
- Automatically creates Jellyfin **BoxSets**
- Automatically updates existing collections
- Downloads TMDb collection posters
- Uploads posters to Jellyfin
- TMDb rate-limit safe
- Interactive **dry-run mode**
- Zero dependencies except `requests`

---

## Installation

```bash
git clone https://github.com/macery12/jellyfin-tmdb-auto-collections
cd jellyfin-tmdb-auto-collections
pip install -r requirements.txt
