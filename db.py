# db.py — PostgreSQL database helper module.
# Uses psycopg v3, the current generation of the PostgreSQL driver (not psycopg2).

import os
import psycopg
from psycopg.rows import dict_row
from flask import g


def _conn_params():
    # Read the connection parameters from environment variables.
    # 127.0.0.1 is used as the host ('localhost' can cause TCP binding issues on Windows).
    
    return {
        "host":   os.getenv("DB_HOST", "127.0.0.1"),
        "port":   os.getenv("DB_PORT", "5432"),
        "dbname": os.getenv("DB_NAME", "hfg_f1db"),
        "user":   os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
    }


def get_db():

    if "db" not in g:
        g.db = psycopg.connect(row_factory=dict_row, **_conn_params())
    return g.db


def close_db(e=None):

    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=None, one=False):

    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, params=None, returning=False):
    # Run INSERT / UPDATE / DELETE and commit.

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(sql, params or ())
            result = cur.fetchone() if returning else None
    except Exception:
        # e.g. an error raised by a stored procedure or trigger: undo the
        # transaction so the connection stays usable, then let the caller decide
        db.rollback()
        raise
    db.commit()
    return result


def init_app(app):
    app.teardown_appcontext(close_db)