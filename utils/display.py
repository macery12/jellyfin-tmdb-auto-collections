# utils/display.py
# Clean display & summary manager

class Display:
    def __init__(self, logger=None):
        self.logger = logger

        # Stored results for summary
        self.missing_requests = []   # (tmdb_id, title, collection)
        self.collections_created = []  # (name, count)
        self.collections_updated = []  # (name, count)

    # ----------------------------------------------------------
    # Basic logging helper
    # ----------------------------------------------------------
    def _log(self, msg):
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    # ----------------------------------------------------------
    # Lightweight progress message
    # ----------------------------------------------------------
    def progress(self, msg):
        # Simple, clean progress output
        self._log(msg)

    # ----------------------------------------------------------
    # TMDb scanning progress e.g. "Building collections (25/431)"
    # ----------------------------------------------------------
    def tmdb_progress(self, current, total):
        self._log(f"Building collections ({current}/{total})")

    # ----------------------------------------------------------
    # Record events for summary
    # ----------------------------------------------------------
    def log_missing_request(self, title, tmdb_id, collection_name):
        self.missing_requests.append((tmdb_id, title, collection_name))

    def log_create_collection(self, name, count):
        self.collections_created.append((name, count))

    def log_update_collection(self, name, count):
        self.collections_updated.append((name, count))

    # ----------------------------------------------------------
    # Final structured summary
    # ----------------------------------------------------------
    def summary(self, movies_scanned, collections_found, missing_detected, log_file_path):
        print("\n=== SUMMARY ===\n")

        def line(label, value):
            print(f"{label:<30} {value}")

        line("Movies scanned:", movies_scanned)
        line("Collections discovered:", collections_found)
        line("Collections created:", len(self.collections_created))
        line("Collections updated:", len(self.collections_updated))
        line("Missing movies detected:", missing_detected)
        line("Jellyseerr requests sent:", len(self.missing_requests))

        print("\nMissing Movies Requested:")
        print("TMDb ID     Title                               Collection")
        print("-------------------------------------------------------------")

        for tmdb_id, title, collection_name in self.missing_requests:
            print(f"{str(tmdb_id):<10}  {title:<35}  {collection_name}")

        print("")
        print(f"Log saved to: {log_file_path}")
        print("")
