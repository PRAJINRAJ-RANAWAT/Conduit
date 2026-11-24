"""Postgres helper. Plain SQL, no ORM: run("SELECT ... WHERE id=%s", (id,)) -> list of dicts."""
import os
from pathlib import Path
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

URL = os.getenv("DATABASE_URL", "postgresql://conduit:conduit@localhost:5432/conduit")
pool = ConnectionPool(URL, min_size=1, max_size=10, open=False, kwargs={"row_factory": dict_row})


def init():
    """Open the pool and create tables."""
    pool.open()
    pool.wait()
    run(Path(__file__).with_name("schema.sql").read_text())


def run(sql: str, args=()):
    with pool.connection() as conn:          # commits when the block ends
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []
