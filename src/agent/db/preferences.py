from agent.db.connection import Database


class PreferenceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def set(self, key: str, value: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO preferences (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
                ("_".join(key.lower().split()), value.strip()),
            )

    def delete(self, key: str) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM preferences WHERE key = ?", ("_".join(key.lower().split()),))
        return cur.rowcount > 0

    def all(self) -> dict[str, str]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT key, value FROM preferences ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}
