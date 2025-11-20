from __future__ import annotations

from typing import List, Tuple


class Display:
    def __init__(self, logger=None) -> None:
        self.logger = logger
        self.missing_requests: List[Tuple[int, str, str]] = []
        self.collections_created: List[Tuple[str, int]] = []
        self.collections_updated: List[Tuple[str, int]] = []

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def progress(self, msg: str) -> None:
        self._log(msg)

    def tmdb_progress(self, current: int, total: int) -> None:
        self._log(f"Building collections ({current}/{total})")

    def log_missing_request(self, title: str, tmdb_id: int, collection_name: str) -> None:
        self.missing_requests.append((tmdb_id, title, collection_name))
        self._log(f"Missing: {title} (TMDb {tmdb_id}) in '{collection_name}'")

    def log_create_collection(self, name: str, count: int) -> None:
        self.collections_created.append((name, count))
        self._log(f"Create → {name} ({count} items)")

    def log_update_collection(self, name: str, count: int) -> None:
        self.collections_updated.append((name, count))
        self._log(f"Update → {name} ({count} items)")

    def summary(
        self,
        movies_scanned: int,
        collections_found: int,
        missing_detected: int,
        log_file_path: str,
        skipped_stats: dict[str, int] | None = None,
    ) -> None:
        print("\n=== SUMMARY ===")
        print(f"Movies scanned:                 {movies_scanned}")
        print(f"Collections discovered:         {collections_found}")
        print(f"Collections created:            {len(self.collections_created)}")
        print(f"Collections updated:            {len(self.collections_updated)}")
        print(f"Missing movies detected:        {missing_detected}")
        print(f"Jellyseerr requests sent:       {len(self.missing_requests)}")

        if skipped_stats:
            total_skipped = sum(skipped_stats.values())
            if total_skipped:
                print("\nSkipped movies:")
                for label, value in skipped_stats.items():
                    if value:
                        print(f"  - {label}: {value}")

        if self.missing_requests:
            print("\nMissing Movies Requested:")
            print("TMDb ID     Title                               Collection")
            print("-------------------------------------------------------------")
            for tmdb_id, title, collection_name in self.missing_requests:
                print(f"{str(tmdb_id):<10}  {title:<35}  {collection_name}")
            print("")

        print(f"Log saved to: {log_file_path}")
