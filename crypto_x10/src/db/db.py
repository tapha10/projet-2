"""SQLite connection helper for the Bybit x10 study."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "db" / "crypto_x10.sqlite"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    return DB_PATH


if __name__ == "__main__":
    p = init_db()
    print(f"Database initialised at {p}")
