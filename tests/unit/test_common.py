"""The foundation all three services share: schema, catalogs, connections.

These behaviours live in common/, so they are asserted once rather than in each
service's file.
"""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common.database import initialize_database
from tests.unit.conftest import ServiceRouter, bearer_headers, login


def test_api_errors_use_accept_language_and_fallback_to_english(api: ServiceRouter):
    # An event read needs no token, so this asserts translation rather than auth;
    # the same handler localizes every APIMessageError.
    english = api.get("/api/v1/events/404")
    assert english.status_code == 404
    assert english.json() == {"detail": "Event not found"}

    spanish = api.get(
        "/api/v1/events/404", headers={"Accept-Language": "es-MX"}
    )
    assert spanish.status_code == 404
    assert spanish.json() == {"detail": "No se encontró el evento"}

    negotiated = api.get(
        "/api/v1/events/404",
        headers={"Accept-Language": "fr-CA, es-ES;q=0.8"},
    )
    assert negotiated.json() == {"detail": "No se encontró el evento"}

    unsupported = api.get(
        "/api/v1/events/404", headers={"Accept-Language": "fr-CA"}
    )
    assert unsupported.json() == {"detail": "Event not found"}


def test_localized_catalogs_define_the_same_messages():
    catalog_directory = Path(__file__).parents[2] / "common" / "locales"
    english = json.loads((catalog_directory / "en.json").read_text(encoding="utf-8"))
    spanish = json.loads((catalog_directory / "es.json").read_text(encoding="utf-8"))

    assert english.keys() == spanish.keys()


def test_existing_users_migrate_to_client_role(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                age INTEGER NOT NULL,
                username TEXT NOT NULL UNIQUE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO users (name, password_hash, email, age, username)
            VALUES ('Legacy Client', 'legacy-hash', 'legacy@example.com', 30, 'legacy')
            """
        )

    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    initialize_database()

    with sqlite3.connect(database_path) as connection:
        role = connection.execute(
            "SELECT role FROM users WHERE username = 'legacy'"
        ).fetchone()[0]
    assert role == "client"


def test_concurrent_reads_do_not_fail(api: ServiceRouter):
    admin_headers = bearer_headers(login(api, "test-admin", "test-admin-password"))
    api.post(
        "/api/v1/events",
        json={
            "name": "Concurrent",
            "date": "2026-12-01",
            "description": "Read by many threads at once",
            "capacity": 5,
            "place": "Bolzano",
        },
        headers=admin_headers,
    )

    def read() -> int:
        return api.get("/api/v1/events").status_code

    with ThreadPoolExecutor(max_workers=24) as pool:
        statuses = list(pool.map(lambda _: read(), range(120)))

    # A per-request connection opened on one threadpool worker and closed on
    # another used to raise sqlite3.ProgrammingError, surfacing as a 500.
    assert set(statuses) == {200}, sorted(set(statuses))
