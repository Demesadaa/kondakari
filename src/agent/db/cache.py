import time

from agent.db.connection import Database


class ApiCache:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, max_age_seconds: float | None = None) -> str | None:
        """Return the cached body, or None if missing or older than max_age_seconds (None = any age)."""
        with self.db.connect() as conn:
            row = conn.execute("SELECT body, fetched_at FROM api_cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if max_age_seconds is not None and time.time() - row["fetched_at"] > max_age_seconds:
            return None
        return row["body"]

    def put(self, key: str, body: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO api_cache (key, body, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET body = excluded.body, fetched_at = excluded.fetched_at",
                (key, body, time.time()),
            )
