import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Append-only: each entry upgrades the schema by one version (tracked in PRAGMA user_version).
# Never edit a migration that has already shipped; add a new one instead.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE threads (
        id         TEXT PRIMARY KEY,
        title      TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_threads_updated_at ON threads(updated_at);

    CREATE TABLE pantry_items (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL CHECK (length(name) > 0),
        quantity   REAL NOT NULL CHECK (quantity > 0),
        unit       TEXT NOT NULL DEFAULT 'pcs',
        location   TEXT NOT NULL DEFAULT 'pantry' CHECK (location IN ('fridge', 'freezer', 'pantry')),
        expires_on TEXT CHECK (expires_on IS NULL OR date(expires_on) = expires_on),
        added_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_pantry_name ON pantry_items(name);
    CREATE INDEX idx_pantry_expires_on ON pantry_items(expires_on);

    -- Recipes seen via TheMealDB; favorite/rating/notes are the user's own data.
    CREATE TABLE recipes (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        category     TEXT NOT NULL DEFAULT '',
        area         TEXT NOT NULL DEFAULT '',
        instructions TEXT NOT NULL DEFAULT '',
        ingredients  TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(ingredients)),
        source_url   TEXT NOT NULL DEFAULT '',
        favorite     INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
        rating       INTEGER CHECK (rating BETWEEN 1 AND 5),
        notes        TEXT NOT NULL DEFAULT '',
        saved_at     TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE meal_plan (
        day       TEXT NOT NULL CHECK (date(day) = day),
        meal      TEXT NOT NULL CHECK (meal IN ('breakfast', 'lunch', 'dinner')),
        recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
        PRIMARY KEY (day, meal)
    );

    CREATE TABLE shopping_list (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        name     TEXT NOT NULL UNIQUE,
        detail   TEXT NOT NULL DEFAULT '',
        added_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE preferences (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE api_cache (
        key        TEXT PRIMARY KEY,
        body       TEXT NOT NULL,
        fetched_at REAL NOT NULL
    );
    """,
    """
    -- Nutrition values per 100 g. 'seed' rows are refreshed from data/foods.json; 'user' rows are never touched.
    CREATE TABLE foods (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        name     TEXT NOT NULL UNIQUE CHECK (length(name) > 0),
        name_ka  TEXT NOT NULL DEFAULT '',
        aliases  TEXT NOT NULL DEFAULT '',
        kcal     REAL NOT NULL CHECK (kcal >= 0),
        protein  REAL NOT NULL CHECK (protein >= 0),
        carbs    REAL NOT NULL CHECK (carbs >= 0),
        fat      REAL NOT NULL CHECK (fat >= 0),
        category TEXT NOT NULL DEFAULT 'other',
        roles    TEXT NOT NULL DEFAULT '',
        tags     TEXT NOT NULL DEFAULT '',
        min_g    REAL NOT NULL DEFAULT 30 CHECK (min_g > 0),
        max_g    REAL NOT NULL DEFAULT 300 CHECK (max_g >= min_g),
        piece_g  REAL CHECK (piece_g IS NULL OR piece_g > 0),
        source   TEXT NOT NULL DEFAULT 'seed' CHECK (source IN ('seed', 'user'))
    );

    CREATE TABLE body_profile (
        id               INTEGER PRIMARY KEY CHECK (id = 1),
        sex              TEXT CHECK (sex IN ('male', 'female')),
        birth_year       INTEGER CHECK (birth_year BETWEEN 1900 AND 2100),
        height_cm        REAL CHECK (height_cm BETWEEN 100 AND 250),
        activity         TEXT CHECK (activity IN ('sedentary', 'light', 'moderate', 'active', 'very_active')),
        goal             TEXT CHECK (goal IN ('lose', 'maintain', 'gain')),
        weekly_rate_kg   REAL CHECK (weekly_rate_kg BETWEEN 0 AND 1.5),
        target_weight_kg REAL CHECK (target_weight_kg BETWEEN 30 AND 300),
        updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE weight_log (
        day       TEXT PRIMARY KEY CHECK (date(day) = day),
        weight_kg REAL NOT NULL CHECK (weight_kg BETWEEN 25 AND 400)
    );

    -- Nutrition is snapshotted at log time so editing a food never rewrites history.
    CREATE TABLE food_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        day       TEXT NOT NULL CHECK (date(day) = day),
        meal      TEXT NOT NULL CHECK (meal IN ('breakfast', 'lunch', 'dinner', 'snack')),
        food_id   INTEGER REFERENCES foods(id) ON DELETE SET NULL,
        food_name TEXT NOT NULL,
        grams     REAL NOT NULL CHECK (grams > 0),
        kcal      REAL NOT NULL CHECK (kcal >= 0),
        protein   REAL NOT NULL CHECK (protein >= 0),
        carbs     REAL NOT NULL CHECK (carbs >= 0),
        fat       REAL NOT NULL CHECK (fat >= 0),
        logged_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_food_log_day ON food_log(day);

    CREATE TABLE workouts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        day         TEXT NOT NULL CHECK (date(day) = day),
        activity    TEXT NOT NULL,
        minutes     REAL NOT NULL CHECK (minutes > 0 AND minutes <= 600),
        intensity   TEXT NOT NULL CHECK (intensity IN ('light', 'moderate', 'vigorous')),
        kcal_burned REAL NOT NULL CHECK (kcal_burned >= 0),
        notes       TEXT NOT NULL DEFAULT '',
        logged_at   TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_workouts_day ON workouts(day);

    CREATE TABLE menu_sets (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        target     TEXT NOT NULL CHECK (json_valid(target)),
        diet       TEXT NOT NULL,
        menus      TEXT NOT NULL CHECK (json_valid(menus)),
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
]


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Short-lived connection; commits on success, rolls back on any exception."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @property
    def schema_version(self) -> int:
        with self.connect() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
                conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
