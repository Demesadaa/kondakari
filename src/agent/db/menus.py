import json

from pydantic import TypeAdapter

from agent.db.connection import Database
from agent.models import Diet, Macros, Menu, MenuSet

_MENUS = TypeAdapter(list[Menu])


class MenuRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, target: Macros, diet: Diet, menus: list[Menu]) -> MenuSet:
        with self.db.connect() as conn:
            row = conn.execute(
                "INSERT INTO menu_sets (target, diet, menus) VALUES (?, ?, ?) RETURNING id, created_at",
                (target.model_dump_json(), diet, _MENUS.dump_json(menus).decode()),
            ).fetchone()
        return MenuSet(id=row["id"], target=target, diet=diet, menus=menus, created_at=row["created_at"])

    def get(self, set_id: int | None = None) -> MenuSet | None:
        """A specific menu set, or the latest one when set_id is None."""
        with self.db.connect() as conn:
            if set_id is None:
                row = conn.execute("SELECT * FROM menu_sets ORDER BY id DESC LIMIT 1").fetchone()
            else:
                row = conn.execute("SELECT * FROM menu_sets WHERE id = ?", (set_id,)).fetchone()
        if row is None:
            return None
        return MenuSet(
            id=row["id"],
            target=Macros(**json.loads(row["target"])),
            diet=row["diet"],
            menus=_MENUS.validate_json(row["menus"]),
            created_at=row["created_at"],
        )
