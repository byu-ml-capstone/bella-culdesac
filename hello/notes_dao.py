"""Data Access Object for the `notes` table.

Encapsulates every SQL statement and Postgres detail so main.py can talk
about notes in terms of Python dicts instead of cursors and tuples.
Pulling this out has three payoffs:

  1. Routes stay thin. `main.py` reads like an HTTP contract, not a SQL
     script. As the app grows this matters — the alternative is one
     giant `main.py` where routing, validation, and data access all
     live in the same functions.
  2. Testing is easier. Tests can patch NotesDAO methods (e.g.
     `patch("main.notes_dao.list_all", return_value=[...])`) instead
     of mocking psycopg's connect / cursor / context-manager stack.
     Faster to write, less brittle when psycopg internals change.
  3. Swapping the storage backend is a one-file change. Want SQLite
     for tests? Point NotesDAO at a different URL. Want SQLAlchemy /
     an ORM? Replace this file, leave main.py alone.

For production traffic you'd hold a connection pool
(psycopg_pool.ConnectionPool) on the DAO instead of opening a new
connection per call — a class-level pool created once at startup, with
each method borrowing a connection from it. Skipped here to keep the
teaching surface small; upgrade when your load justifies it.
"""

import logging
from pathlib import Path

import psycopg

log = logging.getLogger("uvicorn.error")

# Migrations live in hello/migrations/*.sql, sorted lexicographically.
# Convention: `NNN_description.sql` with a zero-padded 3-digit prefix so
# alphabetical sort == intended order (001, 002, ..., 099, 100 all work).
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class NotesDAO:
    """One-connection-per-call DAO backed by Postgres."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    # -- schema management ----------------------------------------------------

    def apply_migrations(self) -> list[str]:
        """Apply any SQL files in migrations/ that haven't been applied yet.

        Idempotent — every applied file's name goes into the `_migrations`
        tracking table, and future runs skip anything already listed there.
        Files run in filename order, so students pick names like
        `001_create_notes.sql`, `002_add_priority.sql`, etc.

        Called from main.py's lifespan hook on every app startup. Both
        `staging` and `main` (production) run the SAME code from the SAME
        commit, so applying migrations at deploy time is how staging and
        prod stay in schema-sync automatically.

        Returns the list of migration filenames that were applied on THIS
        call (empty list if everything was already up to date).
        """
        # Ensure the tracking table exists, then read what's already applied.
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS _migrations ("
                "  name       TEXT         PRIMARY KEY,"
                "  applied_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()"
                ")"
            )
            cur.execute("SELECT name FROM _migrations")
            already_applied = {row[0] for row in cur.fetchall()}

        pending = sorted(
            p for p in MIGRATIONS_DIR.glob("*.sql")
            if p.name not in already_applied
        )

        newly_applied: list[str] = []
        for path in pending:
            sql = path.read_text()
            # One transaction per migration: if the SQL fails halfway, the
            # tracking-table insert also rolls back, so we don't record a
            # migration as applied unless it fully succeeded.
            with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO _migrations (name) VALUES (%s)", (path.name,)
                )
            log.info("applied migration %s", path.name)
            newly_applied.append(path.name)

        if not newly_applied:
            log.info("no pending migrations")
        return newly_applied

    def reset(self) -> None:
        """Destructive — drop the app tables AND the migration tracking table.

        The next apply_migrations() call rebuilds everything from
        migrations/*.sql. Wired to the env-gated /admin/reset endpoint
        for dev use; in production this is behind ALLOW_ADMIN_RESET.
        """
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS notes")
            cur.execute("DROP TABLE IF EXISTS _migrations")
        # Re-apply so the caller gets a working (empty) schema back.
        self.apply_migrations()

    # -- queries --------------------------------------------------------------

    def list_all(self) -> list[dict]:
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT id, body, created_at FROM notes ORDER BY id")
            rows = cur.fetchall()
        return [
            {"id": r[0], "body": r[1], "created_at": r[2].isoformat()}
            for r in rows
        ]

    def insert(self, body: str) -> dict:
        with psycopg.connect(self.database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notes (body) VALUES (%s) RETURNING id, created_at",
                (body,),
            )
            row = cur.fetchone()
        return {"id": row[0], "body": body, "created_at": row[1].isoformat()}
