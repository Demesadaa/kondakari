import uuid

from pydantic import BaseModel

from agent.db.connection import Database

UNTITLED = "New conversation"


class Thread(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class ThreadRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, title: str = UNTITLED) -> Thread:
        with self.db.connect() as conn:
            row = conn.execute(
                "INSERT INTO threads (id, title) VALUES (?, ?) RETURNING *",
                (uuid.uuid4().hex[:12], title),
            ).fetchone()
        return Thread(**dict(row))

    def get(self, thread_id: str) -> Thread | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        return Thread(**dict(row)) if row else None

    def list_recent(self, limit: int = 20) -> list[Thread]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM threads ORDER BY updated_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Thread(**dict(r)) for r in rows]

    def touch(self, thread_id: str, first_message: str | None = None) -> None:
        """Bump updated_at; name the thread after its first user message if still untitled."""
        with self.db.connect() as conn:
            conn.execute("UPDATE threads SET updated_at = datetime('now') WHERE id = ?", (thread_id,))
            if first_message:
                title = first_message.strip().replace("\n", " ")[:60]
                conn.execute(
                    "UPDATE threads SET title = ? WHERE id = ? AND title = ?", (title, thread_id, UNTITLED)
                )
