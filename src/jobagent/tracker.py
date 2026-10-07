"""Tracker: SQLite ledger of applications (replaces the Excel tracker).

Table ``applications``:

    id INTEGER PRIMARY KEY
    company TEXT, title TEXT, url TEXT UNIQUE, track TEXT,
    ats_score INTEGER, status TEXT, applied_at TEXT,
    confirmation_no TEXT, notes TEXT

Status changes go through :meth:`Application.transition` so illegal jumps
are rejected instead of silently written.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from jobagent.models import Application, ApplicationStatus, InvalidTransitionError

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    track TEXT DEFAULT '',
    ats_score INTEGER,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    applied_at TEXT DEFAULT '',
    confirmation_no TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);
"""

_COLUMNS = (
    "id",
    "company",
    "title",
    "url",
    "track",
    "ats_score",
    "status",
    "applied_at",
    "confirmation_no",
    "notes",
)


class Tracker:
    """SQLite-backed application ledger."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Tracker":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writes -----------------------------------------------------------
    def add(self, app: Application) -> int:
        """Insert an application; returns its new id."""
        cur = self._conn.execute(
            "INSERT INTO applications "
            "(company, title, url, track, ats_score, status, applied_at,"
            " confirmation_no, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                app.company,
                app.title,
                app.url,
                app.track,
                app.ats_score,
                app.status.value,
                app.applied_at,
                app.confirmation_no,
                app.notes,
            ),
        )
        self._conn.commit()
        app.id = cur.lastrowid
        return cur.lastrowid

    def update(self, app: Application) -> None:
        """Persist all mutable fields of an existing application."""
        if app.id is None:
            raise ValueError("Application has no id; add() it first")
        self._conn.execute(
            "UPDATE applications SET company=?, title=?, url=?, track=?,"
            " ats_score=?, status=?, applied_at=?, confirmation_no=?,"
            " notes=? WHERE id=?",
            (
                app.company,
                app.title,
                app.url,
                app.track,
                app.ats_score,
                app.status.value,
                app.applied_at,
                app.confirmation_no,
                app.notes,
                app.id,
            ),
        )
        self._conn.commit()

    def set_status(self, app_id: int, new_status: ApplicationStatus) -> Application:
        """Transition an application to ``new_status`` and persist it."""
        app = self.get(app_id)
        if app is None:
            raise KeyError(f"No application with id {app_id}")
        app.transition(new_status)  # raises InvalidTransitionError when illegal
        self.update(app)
        return app

    def delete(self, app_id: int) -> bool:
        """Delete an application; returns True when a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM applications WHERE id=?", (app_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # -- reads ------------------------------------------------------------
    def _row_to_app(self, row: sqlite3.Row) -> Application:
        return Application(
            id=row["id"],
            company=row["company"],
            title=row["title"],
            url=row["url"] or "",
            track=row["track"] or "",
            ats_score=row["ats_score"],
            status=ApplicationStatus(row["status"]),
            applied_at=row["applied_at"] or "",
            confirmation_no=row["confirmation_no"] or "",
            notes=row["notes"] or "",
        )

    def get(self, app_id: int) -> Application | None:
        row = self._conn.execute(
            "SELECT * FROM applications WHERE id=?", (app_id,)
        ).fetchone()
        return self._row_to_app(row) if row else None

    def get_by_url(self, url: str) -> Application | None:
        row = self._conn.execute(
            "SELECT * FROM applications WHERE url=?", (url,)
        ).fetchone()
        return self._row_to_app(row) if row else None

    def list(
        self, status: ApplicationStatus | None = None
    ) -> list[Application]:
        """List applications, optionally filtered by status."""
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM applications ORDER BY id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM applications WHERE status=? ORDER BY id",
                (status.value,),
            ).fetchall()
        return [self._row_to_app(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM applications GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}


__all__ = ["Tracker", "InvalidTransitionError"]
