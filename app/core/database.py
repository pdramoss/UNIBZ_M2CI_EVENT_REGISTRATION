import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    age INTEGER NOT NULL CHECK (age >= 0),
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'client'
        CHECK (role IN ('client', 'administrator'))
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity >= 0),
    place TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('client', 'administrator')),
    username TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS auth_sessions_expires_at
    ON auth_sessions (expires_at);
"""


def _database_path() -> str:
    return os.environ.get("DATABASE_PATH", "data/event_registration.sqlite3")


def connect() -> sqlite3.Connection:
    database_path = _database_path()
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    connection = connect()
    try:
        connection.executescript(SCHEMA)
        user_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)")
        }
        if "role" not in user_columns:
            connection.execute(
                """
                ALTER TABLE users
                ADD COLUMN role TEXT NOT NULL DEFAULT 'client'
                    CHECK (role IN ('client', 'administrator'))
                """
            )
        connection.commit()
    finally:
        connection.close()


def get_db() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()
