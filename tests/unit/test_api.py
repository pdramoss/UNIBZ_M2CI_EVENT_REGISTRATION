import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.database import initialize_database
from app.core.security import hash_session_token
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    with TestClient(app) as test_client:
        yield test_client


def create_user(client: TestClient, username: str = "alex") -> dict:
    response = client.post(
        "/api/v1/users",
        json={
            "name": "Alex",
            "password": "test-password",
            "email": f"{username}@example.com",
            "age": 30,
            "username": username,
        },
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_user_crud_hides_password(client: TestClient, tmp_path):
    user = create_user(client)
    user_id = user["id"]

    assert "password" not in user
    with sqlite3.connect(tmp_path / "test.sqlite3") as connection:
        password_hash = connection.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()[0]
    assert password_hash.startswith("pbkdf2_sha256$")
    assert password_hash != "test-password"
    assert client.get(f"/api/v1/users/{user_id}").json() == user
    assert client.get("/api/v1/users").json() == [user]

    updated = client.patch(f"/api/v1/users/{user_id}", json={"age": 31})
    assert updated.status_code == 200
    assert updated.json()["age"] == 31

    duplicate = client.post(
        "/api/v1/users",
        json={
            "name": "Another Alex",
            "password": "test-password",
            "email": "alex@example.com",
            "age": 25,
            "username": "another",
        },
    )
    assert duplicate.status_code == 409

    assert client.delete(f"/api/v1/users/{user_id}").status_code == 204
    assert client.get(f"/api/v1/users/{user_id}").status_code == 404


def test_event_writes_require_administrator(client: TestClient, monkeypatch):
    admin_headers = bearer_headers(login(client, "test-admin", "test-admin-password"))
    event_payload = {
        "name": "Private meetup",
        "date": "2026-12-01",
        "description": "Admin-only creation",
        "capacity": 10,
        "place": "Bolzano",
    }

    unauthorized = client.post("/api/v1/events", json=event_payload)
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"

    invalid_credentials = client.post(
        "/api/v1/auth/login",
        json={"username": "wrong-admin", "password": "wrong-password"},
    )
    assert invalid_credentials.status_code == 401

    created = client.post(
        "/api/v1/events",
        json=event_payload,
        headers=admin_headers,
    )
    assert created.status_code == 201
    event_id = created.json()["id"]

    unauthorized_update = client.patch(
        f"/api/v1/events/{event_id}", json={"name": "Changed"}
    )
    assert unauthorized_update.status_code == 401
    unauthorized_delete = client.delete(f"/api/v1/events/{event_id}")
    assert unauthorized_delete.status_code == 401

    monkeypatch.delenv("ADMIN_USERNAME")
    monkeypatch.delenv("ADMIN_PASSWORD")
    unavailable_admin = client.post("/api/v1/events", json=event_payload)
    assert unavailable_admin.status_code == 401
    bootstrap_session_still_valid = client.post(
        "/api/v1/events", json=event_payload, headers=admin_headers
    )
    assert bootstrap_session_still_valid.status_code == 201


def test_api_errors_use_accept_language_and_fallback_to_english(client: TestClient):
    english = client.get("/api/v1/users/404")
    assert english.status_code == 404
    assert english.json() == {"detail": "User not found"}

    spanish = client.get(
        "/api/v1/users/404", headers={"Accept-Language": "es-MX"}
    )
    assert spanish.status_code == 404
    assert spanish.json() == {"detail": "No se encontró el usuario"}

    negotiated = client.get(
        "/api/v1/users/404",
        headers={"Accept-Language": "fr-CA, es-ES;q=0.8"},
    )
    assert negotiated.json() == {"detail": "No se encontró el usuario"}

    unsupported = client.get(
        "/api/v1/users/404", headers={"Accept-Language": "fr-CA"}
    )
    assert unsupported.json() == {"detail": "User not found"}


def test_localized_authentication_error_preserves_status_and_headers(
    client: TestClient,
):
    response = client.get(
        "/api/v1/registrations", headers={"Accept-Language": "es"}
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": "Se requiere autenticación con un token Bearer"
    }


def test_login_persists_only_token_hash_and_logout_revokes_session(
    client: TestClient, tmp_path
):
    create_user(client)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alex", "password": "test-password"},
    )

    assert response.status_code == 200
    login_result = response.json()
    token = login_result["access_token"]
    assert login_result["token_type"] == "bearer"
    assert login_result["expires_in"] == 24 * 60 * 60
    assert login_result["role"] == "client"
    assert client.get(
        "/api/v1/registrations", headers=bearer_headers(token)
    ).status_code == 200

    with sqlite3.connect(tmp_path / "test.sqlite3") as connection:
        stored_token_hash = connection.execute(
            "SELECT token_hash FROM auth_sessions"
        ).fetchone()[0]
    assert stored_token_hash == hash_session_token(token)
    assert stored_token_hash != token

    logout_response = client.post(
        "/api/v1/auth/logout", headers=bearer_headers(token)
    )
    assert logout_response.status_code == 204
    assert client.get(
        "/api/v1/registrations", headers=bearer_headers(token)
    ).status_code == 401


def test_expired_session_is_rejected(client: TestClient, tmp_path):
    create_user(client)
    token = login(client, "alex", "test-password")
    with sqlite3.connect(tmp_path / "test.sqlite3") as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = ?",
            ("2000-01-01T00:00:00+00:00",),
        )

    expired = client.get(
        "/api/v1/registrations", headers=bearer_headers(token)
    )
    assert expired.status_code == 401


def test_validation_error_is_unchanged_by_accept_language(client: TestClient):
    default_response = client.post("/api/v1/users", json={})
    spanish_response = client.post(
        "/api/v1/users", json={}, headers={"Accept-Language": "es"}
    )

    assert default_response.status_code == 422
    assert spanish_response.status_code == 422
    assert spanish_response.json() == default_response.json()


def test_localized_catalogs_define_the_same_messages():
    catalog_directory = Path(__file__).parents[2] / "app" / "locales"
    english = json.loads((catalog_directory / "en.json").read_text(encoding="utf-8"))
    spanish = json.loads((catalog_directory / "es.json").read_text(encoding="utf-8"))

    assert english.keys() == spanish.keys()


def test_administrator_can_create_clients_and_administrators(
    client: TestClient, monkeypatch
):
    bootstrap_headers = bearer_headers(
        login(client, "test-admin", "test-admin-password")
    )
    client_payload = {
        "name": "Client One",
        "password": "client-password",
        "email": "client-one@example.com",
        "age": 28,
        "username": "client-one",
    }
    administrator_payload = {
        "name": "Admin One",
        "password": "administrator-password",
        "email": "admin-one@example.com",
        "age": 35,
        "username": "admin-one",
    }

    assert client.post("/api/v1/clients", json=client_payload).status_code == 401
    assert (
        client.post("/api/v1/administrators", json=administrator_payload).status_code
        == 401
    )

    created_client = client.post(
        "/api/v1/clients",
        json=client_payload,
        headers=bootstrap_headers,
    )
    assert created_client.status_code == 201
    assert created_client.json()["role"] == "client"

    created_administrator = client.post(
        "/api/v1/administrators",
        json=administrator_payload,
        headers=bootstrap_headers,
    )
    assert created_administrator.status_code == 201
    admin = created_administrator.json()
    assert admin["role"] == "administrator"

    forbidden_client = client.post(
        "/api/v1/administrators",
        json={**administrator_payload, "username": "other-admin"},
        headers=bearer_headers(login(client, "client-one", "client-password")),
    )
    assert forbidden_client.status_code == 403
    database_admin_headers = bearer_headers(
        login(client, "admin-one", "administrator-password")
    )

    managed_client_payload = {
        **client_payload,
        "email": "managed-client@example.com",
        "username": "managed-client",
    }
    managed_client = client.post(
        "/api/v1/clients",
        json=managed_client_payload,
        headers=database_admin_headers,
    )
    assert managed_client.status_code == 201

    next_admin_payload = {
        **administrator_payload,
        "email": "admin-two@example.com",
        "username": "admin-two",
    }
    next_admin = client.post(
        "/api/v1/administrators",
        json=next_admin_payload,
        headers=database_admin_headers,
    )
    assert next_admin.status_code == 201

    created_event = client.post(
        "/api/v1/events",
        json={
            "name": "Admin-managed event",
            "date": "2026-12-01",
            "description": "Created by a persisted admin",
            "capacity": 10,
            "place": "Bolzano",
        },
        headers=database_admin_headers,
    )
    assert created_event.status_code == 201

    client_registrations = client.get(
        "/api/v1/registrations",
        headers=bearer_headers(login(client, "managed-client", "client-password")),
    )
    assert client_registrations.status_code == 200
    assert client_registrations.json() == []

    assert client.get(f"/api/v1/users/{admin['id']}").status_code == 404
    assert client.delete(f"/api/v1/users/{admin['id']}").status_code == 404
    assert [user["role"] for user in client.get("/api/v1/users").json()] == [
        "client",
        "client",
    ]

    monkeypatch.delenv("ADMIN_USERNAME")
    monkeypatch.delenv("ADMIN_PASSWORD")
    database_admin_client = client.post(
        "/api/v1/clients",
        json={
            **client_payload,
            "email": "database-admin-client@example.com",
            "username": "database-admin-client",
        },
        headers=bearer_headers(login(client, "admin-one", "administrator-password")),
    )
    assert database_admin_client.status_code == 201


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


def test_event_and_registration_crud_enforces_capacity(client: TestClient):
    user = create_user(client)
    admin_headers = bearer_headers(login(client, "test-admin", "test-admin-password"))
    client_headers = bearer_headers(login(client, "alex", "test-password"))
    event_response = client.post(
        "/api/v1/events",
        json={
            "name": "Meetup",
            "date": "2026-12-01",
            "description": "Community meetup",
            "capacity": 1,
            "place": "Bolzano",
        },
        headers=admin_headers,
    )
    assert event_response.status_code == 201
    event = event_response.json()
    event_id = event["id"]
    assert event["date"] == date(2026, 12, 1).isoformat()
    assert client.get(f"/api/v1/events/{event_id}").json() == event
    assert client.get("/api/v1/events").json() == [event]

    updated_event = client.patch(
        f"/api/v1/events/{event_id}",
        json={"place": "Merano"},
        headers=admin_headers,
    )
    assert updated_event.status_code == 200
    assert updated_event.json()["place"] == "Merano"

    registration_response = client.post(
        "/api/v1/registrations",
        json={
            "date": "2026-11-11",
            "event_id": event_id,
        },
        headers=client_headers,
    )
    assert registration_response.status_code == 201
    registration = registration_response.json()
    assert registration["user_id"] == user["id"]
    assert registration["event_id"] == event_id
    assert (
        client.get(
            f"/api/v1/registrations/{registration['id']}",
            headers=client_headers,
        ).json()
        == registration
    )
    assert client.get(
        "/api/v1/registrations", headers=client_headers
    ).json() == [registration]

    create_user(client, "sam")
    second_client_headers = bearer_headers(login(client, "sam", "test-password"))
    full_event = client.post(
        "/api/v1/registrations",
        json={
            "date": "2026-11-12",
            "event_id": event_id,
        },
        headers=second_client_headers,
    )
    assert full_event.status_code == 409

    updated = client.patch(
        f"/api/v1/registrations/{registration['id']}",
        json={"date": "2026-11-13"},
        headers=client_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["date"] == "2026-11-13"

    reduce_capacity = client.patch(
        f"/api/v1/events/{event_id}",
        json={"capacity": 0},
        headers=admin_headers,
    )
    assert reduce_capacity.status_code == 409

    assert (
        client.delete(
            f"/api/v1/registrations/{registration['id']}",
            headers=client_headers,
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/api/v1/registrations/{registration['id']}",
            headers=client_headers,
        ).status_code
        == 404
    )

    cascade_registration = client.post(
        "/api/v1/registrations",
        json={
            "date": "2026-11-14",
            "event_id": event_id,
        },
        headers=client_headers,
    )
    assert cascade_registration.status_code == 201
    assert (
        client.delete(
            f"/api/v1/events/{event_id}",
            headers=admin_headers,
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/api/v1/registrations/{cascade_registration.json()['id']}",
            headers=client_headers,
        ).status_code
        == 404
    )


def test_registration_rejects_missing_event(client: TestClient):
    create_user(client)
    client_headers = bearer_headers(login(client, "alex", "test-password"))
    response = client.post(
        "/api/v1/registrations",
        json={"date": "2026-11-11", "event_id": 404},
        headers=client_headers,
    )
    assert response.status_code == 404


def test_registration_crud_requires_client_and_enforces_ownership(client: TestClient):
    first_user = create_user(client, "alex")
    second_user = create_user(client, "sam")
    first_client_headers = bearer_headers(login(client, "alex", "test-password"))
    second_client_headers = bearer_headers(login(client, "sam", "test-password"))
    admin_headers = bearer_headers(login(client, "test-admin", "test-admin-password"))
    event = client.post(
        "/api/v1/events",
        json={
            "name": "Meetup",
            "date": "2026-12-01",
            "description": "Community meetup",
            "capacity": 10,
            "place": "Bolzano",
        },
        headers=admin_headers,
    ).json()

    unauthenticated = client.get("/api/v1/registrations")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"
    invalid_password = client.get(
        "/api/v1/registrations", headers=bearer_headers("invalid-token")
    )
    assert invalid_password.status_code == 401

    registration_response = client.post(
        "/api/v1/registrations",
        json={"date": "2026-11-11", "event_id": event["id"]},
        headers=first_client_headers,
    )
    assert registration_response.status_code == 201
    registration = registration_response.json()
    assert registration["user_id"] == first_user["id"]

    for method, url, kwargs in (
        ("get", "/api/v1/registrations", {}),
        ("get", f"/api/v1/registrations/{registration['id']}", {}),
        (
            "patch",
            f"/api/v1/registrations/{registration['id']}",
            {"json": {"date": "2026-11-12"}},
        ),
        ("delete", f"/api/v1/registrations/{registration['id']}", {}),
    ):
        response = getattr(client, method)(
            url, headers=second_client_headers, **kwargs
        )
        if method == "get" and url.endswith("/registrations"):
            assert response.status_code == 200
            assert response.json() == []
        else:
            assert response.status_code == 404

    assert client.get(
        "/api/v1/registrations", headers=first_client_headers
    ).json() == [registration]
    changed_owner = client.patch(
        f"/api/v1/registrations/{registration['id']}",
        json={"user_id": second_user["id"]},
        headers=first_client_headers,
    )
    assert changed_owner.status_code == 422
    assert client.get(
        f"/api/v1/registrations/{registration['id']}",
        headers=first_client_headers,
    ).json() == registration


def test_user_persists_across_api_restart(tmp_path, monkeypatch):
    database_path = tmp_path / "persistent.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))

    with TestClient(app) as initial_client:
        user = create_user(initial_client, "persistent")

    with TestClient(app) as restarted_client:
        response = restarted_client.get(f"/api/v1/users/{user['id']}")

    assert response.status_code == 200
    assert response.json() == user
