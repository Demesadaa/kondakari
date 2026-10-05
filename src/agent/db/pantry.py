from datetime import date, timedelta

from agent.db.connection import Database
from agent.matching import normalize
from agent.models import Location, PantryItem


class PantryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        name: str,
        quantity: float,
        unit: str = "pcs",
        location: Location = "pantry",
        expires_on: date | None = None,
    ) -> PantryItem:
        """Insert, or merge into an existing row with the same name, unit, location and expiry."""
        name, unit = normalize(name), normalize(unit) or "pcs"
        expiry = expires_on.isoformat() if expires_on else None
        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM pantry_items WHERE name = ? AND unit = ? AND location = ? AND expires_on IS ?",
                (name, unit, location, expiry),
            ).fetchone()
            if existing:
                row = conn.execute(
                    "UPDATE pantry_items SET quantity = quantity + ? WHERE id = ? RETURNING *",
                    (quantity, existing["id"]),
                ).fetchone()
            else:
                row = conn.execute(
                    "INSERT INTO pantry_items (name, quantity, unit, location, expires_on) "
                    "VALUES (?, ?, ?, ?, ?) RETURNING *",
                    (name, quantity, unit, location, expiry),
                ).fetchone()
        return PantryItem(**dict(row))

    def get(self, item_id: int) -> PantryItem | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM pantry_items WHERE id = ?", (item_id,)).fetchone()
        return PantryItem(**dict(row)) if row else None

    def search(
        self, query: str = "", location: Location | None = None, expiring_within_days: int | None = None
    ) -> list[PantryItem]:
        """Soonest-expiring first; items without an expiry date last."""
        clauses, params = ["name LIKE ?"], [f"%{normalize(query)}%"]
        if location:
            clauses.append("location = ?")
            params.append(location)
        if expiring_within_days is not None:
            clauses.append("expires_on IS NOT NULL AND expires_on <= ?")
            params.append((date.today() + timedelta(days=expiring_within_days)).isoformat())
        sql = (
            f"SELECT * FROM pantry_items WHERE {' AND '.join(clauses)} "
            "ORDER BY expires_on IS NULL, expires_on, name"
        )
        with self.db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [PantryItem(**dict(r)) for r in rows]

    def use(self, item_id: int, quantity: float | None = None) -> PantryItem | None:
        """Deduct quantity; delete the row when used up or when quantity is None. Returns what remains."""
        with self.db.connect() as conn:
            row = conn.execute("SELECT quantity FROM pantry_items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise LookupError(f"No pantry item with id {item_id}")
            if quantity is None or quantity >= row["quantity"] - 1e-9:
                conn.execute("DELETE FROM pantry_items WHERE id = ?", (item_id,))
                return None
            updated = conn.execute(
                "UPDATE pantry_items SET quantity = quantity - ? WHERE id = ? RETURNING *", (quantity, item_id)
            ).fetchone()
        return PantryItem(**dict(updated))
