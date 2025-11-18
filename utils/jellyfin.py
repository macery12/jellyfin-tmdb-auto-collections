import requests


class Jellyfin:
    def __init__(self, base_url, api_key, dry_run=False, logger=None):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.dry_run = dry_run
        self.logger = logger

    def _log(self, msg):
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def _headers(self):
        return {
            "X-Emby-Token": self.key,
            "Accept": "application/json"
        }

    def get(self, path, params=None):
        r = requests.get(
            f"{self.base}{path}",
            headers=self._headers(),
            params=params,
            timeout=30
        )
        r.raise_for_status()
        return r.json()

    def post(self, path, params=None, json=None):
        if self.dry_run:
            self._log(f"[DRY RUN] POST -> {path} params={params}")
            return None

        r = requests.post(
            f"{self.base}{path}",
            headers=self._headers(),
            params=params,
            json=json,
            timeout=30
        )

        if r.status_code not in (200, 201, 204):
            r.raise_for_status()

        try:
            return r.json()
        except Exception:
            return None

    def upload_image(self, item_id, img_type, img_bytes):
        if self.dry_run:
            self._log(f"[DRY RUN] Would upload poster for item {item_id}")
            return

        r = requests.post(
            f"{self.base}/Items/{item_id}/Images/{img_type}",
            headers={"X-Emby-Token": self.key},
            files={"file": ("poster.jpg", img_bytes, "image/jpeg")},
            timeout=30
        )

        if r.status_code not in (200, 204):
            self._log(f"Poster upload failed: {r.text}")

    # ---------- High-level wrapper functions ----------

    def list_users(self):
        return self.get("/Users")

    def get_movies(self, user_id):
        start = 0
        size = 200
        movies = []

        while True:
            d = self.get(
                "/Items",
                {
                    "IncludeItemTypes": "Movie",
                    "Fields": "ProviderIds",
                    "CollapseBoxSetItems": "false",
                    "Recursive": "true",
                    "Limit": size,
                    "StartIndex": start,
                    "UserId": user_id,
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

    def find_collection(self, name, user_id):
        d = self.get(
            "/Items",
            {
                "IncludeItemTypes": "BoxSet",
                "SearchTerm": name,
                "UserId": user_id,
                "Recursive": "true",
            },
        )

        for item in d.get("Items", []):
            if item.get("Name") == name:
                return item["Id"]

        return None

    def create_collection(self, name, ids):
        if not ids:
            return None

        resp = self.post("/Collections", params={"Name": name, "Ids": ",".join(ids)})
        if not resp:
            return None

        return resp.get("Id") or resp.get("id")
