import json
import sqlite3
from datetime import date

from agent.db.connection import Database
from agent.models import MealPlanEntry, MealSlot, Recipe, SavedRecipe

_RECIPE_FIELDS = {"id", "name", "category", "area", "instructions", "source_url"}


def _to_saved(row: sqlite3.Row) -> SavedRecipe:
    data = dict(row)
    data["ingredients"] = json.loads(data["ingredients"])
    data["favorite"] = bool(data["favorite"])
    return SavedRecipe(**data)


class RecipeRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, recipe: Recipe) -> None:
        """Store/refresh recipe content without touching the user's favorite, rating or notes."""
        params = recipe.model_dump(include=_RECIPE_FIELDS)
        params["ingredients"] = json.dumps([i.model_dump() for i in recipe.ingredients])
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO recipes (id, name, category, area, instructions, ingredients, source_url)
                VALUES (:id, :name, :category, :area, :instructions, :ingredients, :source_url)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name, category = excluded.category, area = excluded.area,
                    instructions = excluded.instructions, ingredients = excluded.ingredients,
                    source_url = excluded.source_url
                """,
                params,
            )

    def get(self, recipe_id: str) -> SavedRecipe | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        return _to_saved(row) if row else None

    def mark_favorite(self, recipe_id: str, rating: int | None = None, notes: str | None = None) -> SavedRecipe:
        with self.db.connect() as conn:
            row = conn.execute(
                "UPDATE recipes SET favorite = 1, rating = COALESCE(?, rating), notes = COALESCE(?, notes) "
                "WHERE id = ? RETURNING *",
                (rating, notes, recipe_id),
            ).fetchone()
        if row is None:
            raise LookupError(f"No recipe with id {recipe_id}")
        return _to_saved(row)

    def favorites(self) -> list[SavedRecipe]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM recipes WHERE favorite = 1 ORDER BY rating IS NULL, rating DESC, name"
            ).fetchall()
        return [_to_saved(r) for r in rows]

    def plan(self, day: date, meal: MealSlot, recipe_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO meal_plan (day, meal, recipe_id) VALUES (?, ?, ?) "
                "ON CONFLICT(day, meal) DO UPDATE SET recipe_id = excluded.recipe_id",
                (day.isoformat(), meal, recipe_id),
            )

    def unplan(self, day: date, meal: MealSlot) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute("DELETE FROM meal_plan WHERE day = ? AND meal = ?", (day.isoformat(), meal))
        return cur.rowcount > 0

    def plan_between(self, start: date, end: date) -> list[MealPlanEntry]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.day, m.meal, m.recipe_id, r.name AS recipe_name
                FROM meal_plan m JOIN recipes r ON r.id = m.recipe_id
                WHERE m.day BETWEEN ? AND ?
                ORDER BY m.day, CASE m.meal WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 ELSE 2 END
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [MealPlanEntry(**dict(r)) for r in rows]
