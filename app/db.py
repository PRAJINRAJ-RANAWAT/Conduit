"""Postgres helper. Plain SQL, no ORM: run("SELECT ... WHERE id=%s", (id,)) -> list of dicts."""
import os
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

URL = os.getenv("DATABASE_URL", "postgresql://conduit:conduit@localhost:5432/conduit")
# timeout=2: if Postgres is down, give up after 2s (the API then answers 503) instead of hanging.
# check=...: before handing out a pooled connection, test it, so dead connections are replaced.
pool = ConnectionPool(URL, min_size=1, max_size=10, open=False, timeout=2,
                      check=ConnectionPool.check_connection, kwargs={"row_factory": dict_row})


def init():
    """Open the pool and create tables."""
    pool.open()
    pool.wait()
    # Many processes start at once and all run the schema. A transaction-level advisory lock makes them take
    # turns (it is held until COMMIT), otherwise two "CREATE TABLE IF NOT EXISTS" can collide.
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(777)")
        conn.execute(Path(__file__).with_name("schema.sql").read_text())


def run(sql: str, args=()):
    with pool.connection() as conn:          # commits when the block ends
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []
