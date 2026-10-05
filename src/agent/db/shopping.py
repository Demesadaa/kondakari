from agent.db.connection import Database
from agent.matching import normalize
from agent.models import ShoppingItem


class ShoppingRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, name: str, detail: str = "") -> None:
        """Merge by name; append detail unless it is already recorded (keeps regeneration idempotent)."""
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO shopping_list (name, detail) VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET detail = CASE
                    WHEN excluded.detail = '' OR instr(detail, excluded.detail) > 0 THEN detail
                    WHEN detail = '' THEN excluded.detail
                    ELSE detail || '; ' || excluded.detail
                END
                """,
                (normalize(name), detail.strip()),
            )

    def items(self) -> list[ShoppingItem]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT id, name, detail FROM shopping_list ORDER BY name").fetchall()
        return [ShoppingItem(**dict(r)) for r in rows]

    def remove(self, item_ids: list[int]) -> list[ShoppingItem]:
        if not item_ids:
            return []
        placeholders = ",".join("?" * len(item_ids))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"DELETE FROM shopping_list WHERE id IN ({placeholders}) RETURNING id, name, detail", item_ids
            ).fetchall()
        return [ShoppingItem(**dict(r)) for r in rows]
