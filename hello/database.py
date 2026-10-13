from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

log = logging.getLogger("culdesac")


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def apply_migrations() -> list[str]:
    """Apply numbered SQL migrations, one transaction per file."""
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS _migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )"""
        )
        applied = {
            row[0] for row in conn.execute("SELECT name FROM _migrations").fetchall()
        }

    newly_applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        with psycopg.connect(settings.database_url) as conn:
            conn.execute(sql)
            conn.execute("INSERT INTO _migrations (name) VALUES (%s)", (path.name,))
        log.info("migration_applied migration=%s", path.name)
        newly_applied.append(path.name)
    return newly_applied


def initialize_database() -> None:
    """Fail closed after bounded startup retries."""
    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            apply_migrations()
            settings.attachments_dir.mkdir(parents=True, exist_ok=True)
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            log.warning("database_unavailable attempt=%s", attempt)
            if attempt < 5:
                time.sleep(2)
    raise RuntimeError("database initialization failed") from last_error


def database_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def reset_database() -> None:
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            """DO $$ DECLARE r RECORD; BEGIN
            FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname='public'
                      AND tablename <> '_migrations') LOOP
                EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
            END LOOP; END $$;"""
        )
        conn.execute("DROP TABLE IF EXISTS _migrations")
    if settings.attachments_dir.exists():
        for child in settings.attachments_dir.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
    initialize_database()
