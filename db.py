import os
import sqlite3
from flask import current_app, g

ROOT = os.path.dirname(os.path.abspath(__file__))


def connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn):
    with open(os.path.join(ROOT, "schema.sql")) as f:
        conn.executescript(f.read())
    conn.commit()


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
