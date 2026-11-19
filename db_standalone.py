#db_standalone.py — Standalone PostgreSQL connection for non-Flask (CLI) scripts.

#The Flask db.py needs a request context; data_loader.py and the backfill scripts
#run on their own, so they use this helper instead.

import os
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

load_dotenv()


def connect():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "hfg_f1db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        row_factory=dict_row,
    )