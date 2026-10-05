import difflib
import json
import sqlite3
from pathlib import Path

from agent.db.connection import Database
from agent.matching import normalize, tokens
from agent.models import Food

_LIST_FIELDS = ("aliases", "roles", "tags")
_COLUMNS = ("name", "name_ka", "aliases", "kcal", "protein", "carbs", "fat",
            "category", "roles", "tags", "min_g", "max_g", "piece_g")


def _to_food(row: sqlite3.Row) -> Food:
    data = dict(row)
    for field in _LIST_FIELDS:
        data[field] = [v for v in data[field].split(",") if v]
    return Food(**data)


def _row_params(food: dict) -> dict:
    params = {c: food.get(c) for c in _COLUMNS}
    params["name"] = normalize(food["name"])
    params["name_ka"] = (food.get("name_ka") or "").strip()
    for field in _LIST_FIELDS:
        params[field] = ",".join(normalize(v) for v in food.get(field) or [])
    params["category"] = food.get("category") or "other"
    params["min_g"] = food.get("min_g") or 30
    params["max_g"] = food.get("max_g") or 300
    return params


def _score(food: Food, query: str) -> int:
    names = [food.name, food.name_ka.lower(), *food.aliases]
    if query in names:
        return 4
    if any(n.startswith(query) for n in names if n):
        return 3
    if any(query in n for n in names if n):
        return 2
    q = tokens(query)
    if q and any(q <= tokens(n) for n in names if n):
        return 1
    return 0


class FoodRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def seed(self, path: Path) -> int:
        """Idempotent: refreshes seed rows from the JSON file, never overwrites user-defined foods."""
        foods = json.loads(path.read_text(encoding="utf-8"))
        cols = ", ".join(_COLUMNS)
        values = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "name")
        with self.db.connect() as conn:
            conn.executemany(
                f"INSERT INTO foods ({cols}, source) VALUES ({values}, 'seed') "
                f"ON CONFLICT(name) DO UPDATE SET {updates} WHERE foods.source = 'seed'",
                [_row_params(f) for f in foods],
            )
        return len(foods)

    def all(self) -> list[Food]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM foods ORDER BY name").fetchall()
        return [_to_food(r) for r in rows]

    def get(self, food_id: int) -> Food | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
        return _to_food(row) if row else None

    def search(self, query: str, limit: int = 10) -> list[Food]:
        q = normalize(query)
        scored = [(s, f) for f in self.all() if (s := _score(f, q)) > 0]
        scored.sort(key=lambda sf: (-sf[0], len(sf[1].name)))
        return [f for _, f in scored[:limit]]

    def resolve(self, name: str) -> Food:
        """Best match by English/Georgian name or alias; raises LookupError with suggestions."""
        if hits := self.search(name, limit=1):
            return hits[0]
        foods = self.all()
        candidates = {n: f.name for f in foods for n in (f.name, f.name_ka, *f.aliases) if n}
        close = difflib.get_close_matches(normalize(name), list(candidates), n=3, cutoff=0.6)
        hint = f" Did you mean: {', '.join(sorted({candidates[c] for c in close}))}?" if close else ""
        raise LookupError(f"Unknown food {name!r}.{hint} Otherwise add it with add_custom_food (values per 100 g).")

    def add_custom(
        self,
        name: str,
        kcal: float,
        protein: float,
        carbs: float,
        fat: float,
        name_ka: str = "",
        piece_g: float | None = None,
    ) -> Food:
        params = _row_params({
            "name": name, "name_ka": name_ka, "kcal": kcal, "protein": protein, "carbs": carbs, "fat": fat,
            "category": "custom", "piece_g": piece_g,
        })
        cols = ", ".join(_COLUMNS)
        values = ", ".join(f":{c}" for c in _COLUMNS)
        updates = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS if c != "name")
        with self.db.connect() as conn:
            row = conn.execute(
                f"INSERT INTO foods ({cols}, source) VALUES ({values}, 'user') "
                f"ON CONFLICT(name) DO UPDATE SET {updates}, source = 'user' RETURNING *",
                params,
            ).fetchone()
        return _to_food(row)
