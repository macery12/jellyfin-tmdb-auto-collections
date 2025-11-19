class Display:
    def __init__(self, logger=None):
        self.logger = logger
        self.missing_requests = []
        self.collections_created = []
        self.collections_updated = []

    def _log(self, msg):
        if self.logger:
            self.logger(msg)
        else:
            print(msg)

    def progress(self, msg):
        self._log(msg)

    def tmdb_progress(self, current, total):
        self._log(f"Building collections ({current}/{total})")

    def log_missing_request(self, title, tmdb_id, collection_name):
        self.missing_requests.append((tmdb_id, title, collection_name))

    def log_create_collection(self, name, count):
        self.collections_created.append((name, count))

    def log_update_collection(self, name, count):
        self.collections_updated.append((name, count))

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

        print()
        print(f"Log saved to: {log_file_path}")
        print()
