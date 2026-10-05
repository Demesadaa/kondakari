from datetime import date

from agent.db.connection import Database
from agent.models import BodyProfile, Food, FoodLogEntry, Intensity, LogMeal, Macros, WeightEntry, Workout

_PROFILE_FIELDS = tuple(BodyProfile.model_fields)


class ProfileRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self) -> BodyProfile:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM body_profile WHERE id = 1").fetchone()
        return BodyProfile(**dict(row)) if row else BodyProfile()

    def update(self, **fields) -> BodyProfile:
        """Partial update; None values are ignored."""
        changes = {k: v for k, v in fields.items() if k in _PROFILE_FIELDS and v is not None}
        if changes:
            cols = ", ".join(changes)
            values = ", ".join(f":{k}" for k in changes)
            updates = ", ".join(f"{k} = excluded.{k}" for k in changes)
            with self.db.connect() as conn:
                conn.execute(
                    f"INSERT INTO body_profile (id, {cols}) VALUES (1, {values}) "
                    f"ON CONFLICT(id) DO UPDATE SET {updates}, updated_at = datetime('now')",
                    changes,
                )
        return self.get()


class WeightRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def log(self, day: date, weight_kg: float) -> WeightEntry:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO weight_log (day, weight_kg) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET weight_kg = excluded.weight_kg",
                (day.isoformat(), weight_kg),
            )
        return WeightEntry(day=day, weight_kg=weight_kg)

    def latest(self) -> WeightEntry | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM weight_log ORDER BY day DESC LIMIT 1").fetchone()
        return WeightEntry(**dict(row)) if row else None

    def between(self, start: date, end: date) -> list[WeightEntry]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM weight_log WHERE day BETWEEN ? AND ? ORDER BY day", (start.isoformat(), end.isoformat())
            ).fetchall()
        return [WeightEntry(**dict(r)) for r in rows]


class FoodLogRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, day: date, meal: LogMeal, food: Food, grams: float) -> FoodLogEntry:
        m = food.macros(grams)
        with self.db.connect() as conn:
            row = conn.execute(
                "INSERT INTO food_log (day, meal, food_id, food_name, grams, kcal, protein, carbs, fat) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *",
                (day.isoformat(), meal, food.id, food.name, grams,
                 round(m.kcal, 1), round(m.protein, 1), round(m.carbs, 1), round(m.fat, 1)),
            ).fetchone()
        return FoodLogEntry(**dict(row))

    def for_day(self, day: date) -> list[FoodLogEntry]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM food_log WHERE day = ? "
                "ORDER BY CASE meal WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'snack' THEN 2 ELSE 3 END, id",
                (day.isoformat(),),
            ).fetchall()
        return [FoodLogEntry(**dict(r)) for r in rows]

    def delete(self, entry_id: int) -> FoodLogEntry:
        with self.db.connect() as conn:
            row = conn.execute("DELETE FROM food_log WHERE id = ? RETURNING *", (entry_id,)).fetchone()
        if row is None:
            raise LookupError(f"No food log entry with id {entry_id}")
        return FoodLogEntry(**dict(row))

    def daily_totals(self, start: date, end: date) -> dict[date, Macros]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT day, SUM(kcal) AS kcal, SUM(protein) AS protein, SUM(carbs) AS carbs, SUM(fat) AS fat "
                "FROM food_log WHERE day BETWEEN ? AND ? GROUP BY day ORDER BY day",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return {date.fromisoformat(r["day"]): Macros(**{k: r[k] for k in ("kcal", "protein", "carbs", "fat")})
                for r in rows}


class WorkoutRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self, day: date, activity: str, minutes: float, intensity: Intensity, kcal_burned: float, notes: str = ""
    ) -> Workout:
        with self.db.connect() as conn:
            row = conn.execute(
                "INSERT INTO workouts (day, activity, minutes, intensity, kcal_burned, notes) "
                "VALUES (?, ?, ?, ?, ?, ?) RETURNING *",
                (day.isoformat(), activity.strip().lower(), minutes, intensity, kcal_burned, notes.strip()),
            ).fetchone()
        return Workout(**dict(row))

    def between(self, start: date, end: date) -> list[Workout]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workouts WHERE day BETWEEN ? AND ? ORDER BY day, id",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [Workout(**dict(r)) for r in rows]
