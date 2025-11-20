from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests


class Jellyfin:
    def __init__(self, base_url: str, api_key: str, dry_run: bool = False, logger=None, debug: bool = False) -> None:
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.dry_run = dry_run
        self.logger = logger
        self.debug = debug

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Emby-Token": self.key,
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base}{path}"
        try:
            r = requests.get(url, headers=self._headers(), params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self._log(f"Jellyfin GET failed: {url} ({e})")
            return None

    def post(self, path: str, params: Optional[Dict[str, Any]] = None, json_body: Any = None) -> Any:
        url = f"{self.base}{path}"
        if self.dry_run:
            self._log(f"[DRY RUN] POST -> {path} params={params}")
            return None
        try:
            r = requests.post(url, headers=self._headers(), params=params, json=json_body, timeout=15)
            r.raise_for_status()
            if r.text:
                try:
                    return r.json()
                except Exception:
                    return None
            return None
        except Exception as e:
            self._log(f"Jellyfin POST failed: {url} ({e})")
            return None

    def list_users(self) -> List[Dict[str, Any]]:
        data = self.get("/Users")
        if not isinstance(data, list):
            return []
        return data

    def get_movies(self, user_id: str) -> List[Dict[str, Any]]:
        params = {
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": "ProviderIds",
            "UserId": user_id,
        }
        data = self.get("/Items", params=params)
        if not data:
            return []
        return data.get("Items", [])

    def find_collection(self, name: str, user_id: str) -> Optional[str]:
        params = {
            "IncludeItemTypes": "BoxSet",
            "Recursive": "true",
            "SearchTerm": name,
            "UserId": user_id,
        }
        data = self.get("/Items", params=params)
        if not data:
            return None

        for item in data.get("Items", []):
            if item.get("Name") == name:
                return item.get("Id")

        return None

    def create_collection(self, name: str, ids: List[str]) -> Optional[str]:
        if not ids:
            return None
        resp = self.post("/Collections", params={"Name": name, "Ids": ",".join(ids)})
        if not resp:
            return None
        return resp.get("Id") or resp.get("id")

    def upload_image(self, item_id: str, img_type: str, content: bytes) -> bool:
        if self.dry_run:
            self._log(f"[DRY RUN] Would upload {img_type} image for item {item_id}")
            return True

        url = f"{self.base}/Items/{item_id}/Images/{img_type}"
        headers = {"X-Emby-Token": self.key, "Content-Type": "image/jpeg"}

        try:
            r = requests.post(url, headers=headers, data=content, timeout=30)
            r.raise_for_status()
            return True
        except Exception as e:
            self._log(f"Poster upload failed for {item_id}: {e}")
            return False

    def has_primary_image(self, item_id: str) -> bool:
        url = f"{self.base}/Items/{item_id}/Images/Primary"
        try:
            r = requests.get(url, headers={"X-Emby-Token": self.key}, timeout=10)
            if r.status_code == 200:
                return True
            if self.debug:
                self._log(f"Primary image check status for {item_id}: {r.status_code}")
            return False
        except Exception as e:
            if self.debug:
                self._log(f"Primary image check failed for {item_id}: {e}")
            return False
