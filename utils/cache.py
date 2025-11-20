from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict, Iterable, Set


class JsonCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: Dict[str, Dict[str, Any]] = {"movie": {}, "collection": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return

        if "movie" in raw or "collection" in raw:
            movie = raw.get("movie") or {}
            collection = raw.get("collection") or {}
            self.data["movie"].update({str(k): v for k, v in movie.items()})
            self.data["collection"].update({str(k): v for k, v in collection.items()})
        else:
            movie: Dict[str, Any] = {}
            collection: Dict[str, Any] = {}
            for key, val in raw.items():
                if isinstance(key, str) and key.startswith("/movie/"):
                    tmdb_id = key.split("/")[-1]
                    movie[str(tmdb_id)] = val
                elif isinstance(key, str) and key.startswith("/collection/"):
                    cid = key.split("/")[-1]
                    collection[str(cid)] = val
            self.data["movie"].update(movie)
            self.data["collection"].update(collection)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def get_movie(self, tmdb_id: int | str) -> Any:
        return self.data["movie"].get(str(tmdb_id))

    def set_movie(self, tmdb_id: int | str, payload: Dict[str, Any]) -> None:
        self.data["movie"][str(tmdb_id)] = payload
        self.save()

    def get_collection(self, cid: int | str) -> Any:
        return self.data["collection"].get(str(cid))

    def set_collection(self, cid: int | str, payload: Dict[str, Any]) -> None:
        self.data["collection"][str(cid)] = payload
        self.save()

    def has_movie(self, tmdb_id: int | str) -> bool:
        return str(tmdb_id) in self.data["movie"]

    def has_collection(self, cid: int | str) -> bool:
        return str(cid) in self.data["collection"]

    def prune_movies(self, valid_ids: Iterable[int | str]) -> None:
        valid: Set[str] = {str(v) for v in valid_ids}
        current = set(self.data["movie"].keys())
        to_remove = current - valid
        if not to_remove:
            return
        for key in to_remove:
            self.data["movie"].pop(key, None)
        self.save()
