import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.errors import DomainError
from app.sources.base import utcnow


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS resources (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS resource_kind_seq ON resources(kind, seq)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status INTEGER NOT NULL, payload TEXT NOT NULL)"
            )
            # A process restart must never leave jobs permanently running.
            for row in db.execute("SELECT id,payload FROM resources WHERE kind='job'").fetchall():
                job = json.loads(row["payload"])
                if job["status"] in ("queued", "running"):
                    job.update(
                        status="failed",
                        error={"code": "PROCESS_RESTARTED", "message": "Worker interrupted by restart"},
                    )
                    db.execute("UPDATE resources SET payload=? WHERE id=?", (json.dumps(job), row["id"]))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, kind: str, identifier: str, payload: dict, update=False):
        with self.connect() as db:
            if update:
                db.execute(
                    "UPDATE resources SET payload=? WHERE id=? AND kind=?",
                    (json.dumps(payload, allow_nan=False), identifier, kind),
                )
            else:
                db.execute(
                    "INSERT INTO resources(id,kind,created_at,payload) VALUES (?,?,?,?)",
                    (identifier, kind, utcnow(), json.dumps(payload, allow_nan=False)),
                )
        return payload

    def get(self, kind: str, identifier: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM resources WHERE id=? AND kind=?", (identifier, kind)
            ).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", f"{kind.capitalize()} not found", 404)
        return json.loads(row["payload"])

    def history(self, limit=50, cursor=None, verdict=None, source=None):
        clauses, args = ["kind='verification'"], []
        if cursor:
            try:
                args.append(int(cursor))
            except ValueError as exc:
                raise DomainError("INVALID_CURSOR", "History cursor is invalid") from exc
            clauses.append("seq < ?")
        if verdict:
            clauses.append("json_extract(payload, '$.verdict') = ?")
            args.append(verdict)
        if source:
            clauses.append("json_extract(payload, '$.source') = ?")
            args.append(source)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT seq,payload FROM resources WHERE {' AND '.join(clauses)} ORDER BY seq DESC LIMIT ?",
                (*args, limit + 1),
            ).fetchall()
        return {
            "items": [json.loads(row["payload"]) for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1]["seq"]) if len(rows) > limit else None,
        }
