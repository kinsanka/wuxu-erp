import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).parent
DATABASE_URL = os.getenv("DATABASE_URL", "")
POSTGRES = bool(DATABASE_URL) or os.getenv("ERP_POSTGRES") == "1"


class Database:
    def __init__(self):
        if POSTGRES:
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(DATABASE_URL, connect_timeout=5, row_factory=dict_row)
        else:
            path = Path(os.getenv("ERP_SQLITE", "erp-preview.sqlite3"))
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path, timeout=10)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql, args=()):
        if POSTGRES:
            return self.conn.execute(sql, args) if args else self.conn.execute(sql)
        return self.conn.execute(sql.replace("%s", "?"), args)

    def all(self, sql, args=()):
        return [dict(row) for row in self.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        row = self.execute(sql, args).fetchone()
        return dict(row) if row is not None else None


@contextmanager
def transaction(write=False):
    db = Database()
    try:
        if write:
            if POSTGRES:
                db.execute("SELECT pg_advisory_xact_lock(24603298)")
            else:
                db.execute("BEGIN IMMEDIATE")
        elif POSTGRES:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        else:
            db.execute("BEGIN")
        yield db
        if write:
            db.conn.commit()
    finally:
        db.conn.close()


def initialize(db):
    for statement in (ROOT / "schema.sql").read_text().split(";"):
        if statement.strip():
            db.execute(statement)
    if not db.one("SELECT value FROM settings WHERE key='accepted_receipts_v1'"):
        db.execute(
            "INSERT INTO accepted_receipts(movement_id,accepted) "
            "SELECT m.id,COALESCE((SELECT MIN(e.created) FROM inspections e WHERE e.lot_id=l.id "
            "AND e.verdict='released' AND e.created>=m.created),m.created) FROM movements m "
            "JOIN lots l ON l.id=m.lot_id JOIN items i ON i.id=l.item_id WHERE m.kind='收货' "
            "AND (i.quality=0 OR l.status='released' OR EXISTS (SELECT 1 FROM inspections e WHERE e.lot_id=l.id "
            "AND e.verdict='released' AND e.created>=m.created)) ON CONFLICT(movement_id) DO NOTHING"
        )
        db.execute("INSERT INTO settings VALUES ('accepted_receipts_v1','1')")
