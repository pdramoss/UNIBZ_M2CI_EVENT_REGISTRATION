"""The accounts service: authentication, sessions and account records."""

import sqlite3

from fastapi.testclient import TestClient

from common.security import hash_session_token
from tests.unit.conftest import (
    SERVICE_APPS,
    ServiceRouter,
    bearer_headers,
    create_user,
    login,
)


def test_user_crud_hides_password(api: ServiceRouter, tmp_path):
    user = create_user(api)
    user_id = user["id"]
    # Reading or changing a user record needs the owner or an administrator.
    admin = bearer_headers(login(api, "test-admin", "test-admin-password"))

    assert "password" not in user
    with sqlite3.connect(tmp_path / "test.sqlite3") as connection:
        password_hash = connection.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()[0]
    assert password_hash.startswith("pbkdf2_sha256$")
    assert password_hash != "test-password"
    assert api.get(f"/api/v1/users/{user_id}", headers=admin).json() == user
    assert api.get("/api/v1/users", headers=admin).json() == [user]

    updated = api.patch(
        f"/api/v1/users/{user_id}", json={"age": 31}, headers=admin
    )
    assert updated.status_code == 200
    assert updated.json()["age"] == 31

    duplicate = api.post(
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

    assert api.delete(f"/api/v1/users/{user_id}", headers=admin).status_code == 204
    assert api.get(f"/api/v1/users/{user_id}", headers=admin).status_code == 404


def test_login_persists_only_token_hash_and_logout_revokes_session(
    api: ServiceRouter, tmp_path
):
    create_user(api)
    response = api.post(
        "/api/v1/auth/login",
        json={"username": "alex", "password": "test-password"},
    )

    assert response.status_code == 200
    login_result = response.json()
    token = login_result["access_token"]
    assert login_result["token_type"] == "bearer"
    assert login_result["expires_in"] == 24 * 60 * 60
    assert login_result["role"] == "client"
    assert api.get(
        "/api/v1/registrations", headers=bearer_headers(token)
    ).status_code == 200

    with sqlite3.connect(tmp_path / "test.sqlite3") as connection:
        stored_token_hash = connection.execute(
            "SELECT token_hash FROM auth_sessions"
        ).fetchone()[0]
    assert stored_token_hash == hash_session_token(token)
    assert stored_token_hash != token

    logout_response = api.post(
        "/api/v1/auth/logout", headers=bearer_headers(token)
    )
    assert logout_response.status_code == 204
    assert api.get(
        "/api/v1/registrations", headers=bearer_headers(token)
    ).status_code == 401


def test_expired_session_is_rejected(api: ServiceRouter, tmp_path):
    create_user(api)
    token = login(api, "alex", "test-password")
    with sqlite3.connect(tmp_path / "test.sqlite3") as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = ?",
            ("2000-01-01T00:00:00+00:00",),
        )

    expired = api.get(
        "/api/v1/registrations", headers=bearer_headers(token)
    )
    assert expired.status_code == 401


def test_validation_error_is_unchanged_by_accept_language(api: ServiceRouter):
    default_response = api.post("/api/v1/users", json={})
    spanish_response = api.post(
        "/api/v1/users", json={}, headers={"Accept-Language": "es"}
    )

    assert default_response.status_code == 422
    assert spanish_response.status_code == 422
    assert spanish_response.json() == default_response.json()


def test_administrator_can_create_clients_and_administrators(
    api: ServiceRouter, monkeypatch
):
    bootstrap_headers = bearer_headers(
        login(api, "test-admin", "test-admin-password")
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

    assert api.post("/api/v1/clients", json=client_payload).status_code == 401
    assert (
        api.post("/api/v1/administrators", json=administrator_payload).status_code
        == 401
    )

    created_client = api.post(
        "/api/v1/clients",
        json=client_payload,
        headers=bootstrap_headers,
    )
    assert created_client.status_code == 201
    assert created_client.json()["role"] == "client"

    created_administrator = api.post(
        "/api/v1/administrators",
        json=administrator_payload,
        headers=bootstrap_headers,
    )
    assert created_administrator.status_code == 201
    admin = created_administrator.json()
    assert admin["role"] == "administrator"

    forbidden_client = api.post(
        "/api/v1/administrators",
        json={**administrator_payload, "username": "other-admin"},
        headers=bearer_headers(login(api, "client-one", "client-password")),
    )
    assert forbidden_client.status_code == 403
    database_admin_headers = bearer_headers(
        login(api, "admin-one", "administrator-password")
    )

    managed_client_payload = {
        **client_payload,
        "email": "managed-client@example.com",
        "username": "managed-client",
    }
    managed_client = api.post(
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
    next_admin = api.post(
        "/api/v1/administrators",
        json=next_admin_payload,
        headers=database_admin_headers,
    )
    assert next_admin.status_code == 201

    created_event = api.post(
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

    client_registrations = api.get(
        "/api/v1/registrations",
        headers=bearer_headers(login(api, "managed-client", "client-password")),
    )
    assert client_registrations.status_code == 200
    assert client_registrations.json() == []

    assert api.get(
        f"/api/v1/users/{admin['id']}", headers=database_admin_headers
    ).status_code == 404
    assert api.delete(
        f"/api/v1/users/{admin['id']}", headers=database_admin_headers
    ).status_code == 404
    assert [
        user["role"]
        for user in api.get(
            "/api/v1/users", headers=database_admin_headers
        ).json()
    ] == ["client", "client"]

    monkeypatch.delenv("ADMIN_USERNAME")
    monkeypatch.delenv("ADMIN_PASSWORD")
    database_admin_client = api.post(
        "/api/v1/clients",
        json={
            **client_payload,
            "email": "database-admin-client@example.com",
            "username": "database-admin-client",
        },
        headers=bearer_headers(login(api, "admin-one", "administrator-password")),
    )
    assert database_admin_client.status_code == 201


def test_user_persists_across_api_restart(service_environment):
    # The record has to outlive the process that wrote it: the database is a
    # volume, not the container's filesystem.
    payload = {
        "name": "Alex",
        "password": "test-password",
        "email": "persistent@example.com",
        "age": 30,
        "username": "persistent",
    }

    with TestClient(SERVICE_APPS["accounts"]) as initial_client:
        created = initial_client.post("/api/v1/users", json=payload)
        assert created.status_code == 201
        user = created.json()

    with TestClient(SERVICE_APPS["accounts"]) as restarted_client:
        # The account can still authenticate after the restart, and reads itself
        # through the token rather than a remembered id.
        restarted = ServiceRouter({"accounts": restarted_client})
        token = login(restarted, "persistent", "test-password")
        response = restarted_client.get(
            "/api/v1/users/me", headers=bearer_headers(token)
        )

    assert response.status_code == 200
    assert response.json() == user


def test_users_me_reads_the_account_behind_the_token(api: ServiceRouter):
    user = create_user(api)
    headers = bearer_headers(login(api, "alex", "test-password"))

    response = api.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == user
    assert "password" not in response.json()
    # "me" must not be swallowed by /users/{user_id}, which cannot parse it.
    assert api.get("/api/v1/users/me").status_code == 401


def test_users_me_updates_without_knowing_the_id(api: ServiceRouter):
    create_user(api)
    headers = bearer_headers(login(api, "alex", "test-password"))

    renamed = api.patch(
        "/api/v1/users/me", json={"name": "Alexandra"}, headers=headers
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Alexandra"

    changed = api.patch(
        "/api/v1/users/me", json={"password": "a-new-password"}, headers=headers
    )
    assert changed.status_code == 200
    assert login(api, "alex", "a-new-password")

    # UserPatch has no role field and APIModel forbids extras, so a client
    # cannot promote itself through its own profile.
    escalation = api.patch(
        "/api/v1/users/me", json={"role": "administrator"}, headers=headers
    )
    assert escalation.status_code == 422
    assert api.get("/api/v1/users/me", headers=headers).json()["role"] == "client"


def test_a_client_reaches_only_its_own_record(api: ServiceRouter):
    mine = create_user(api, "mine")
    theirs = create_user(api, "theirs")
    headers = bearer_headers(login(api, "mine", "test-password"))

    assert api.get(f"/api/v1/users/{mine['id']}", headers=headers).status_code == 200
    assert api.get(f"/api/v1/users/{theirs['id']}", headers=headers).status_code == 403
    assert (
        api.patch(
            f"/api/v1/users/{theirs['id']}", json={"age": 1}, headers=headers
        ).status_code
        == 403
    )
    assert (
        api.delete(f"/api/v1/users/{theirs['id']}", headers=headers).status_code == 403
    )
    assert api.get(f"/api/v1/users/{theirs['id']}", headers=headers).status_code == 403

    # An administrator may reach any of them.
    admin = bearer_headers(login(api, "test-admin", "test-admin-password"))
    assert api.get(f"/api/v1/users/{theirs['id']}", headers=admin).status_code == 200


def test_the_client_directory_is_not_public(api: ServiceRouter):
    create_user(api)

    assert api.get("/api/v1/users").status_code == 401
    assert (
        api.get(
            "/api/v1/users",
            headers=bearer_headers(login(api, "alex", "test-password")),
        ).status_code
        == 403
    )
    assert (
        api.get(
            "/api/v1/users",
            headers=bearer_headers(login(api, "test-admin", "test-admin-password")),
        ).status_code
        == 200
    )
    # Signing up stays open; it is how a client gets an account at all.
    assert api.post(
        "/api/v1/users",
        json={
            "name": "Walk In",
            "password": "test-password",
            "email": "walkin@example.com",
            "age": 22,
            "username": "walkin",
        },
    ).status_code == 201


def test_the_bootstrap_administrator_has_no_profile(api: ServiceRouter):
    # It authenticates from environment variables and has no users row, so there
    # is nothing for users/me to return.
    headers = bearer_headers(login(api, "test-admin", "test-admin-password"))

    response = api.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Account not found"}
    assert api.patch(
        "/api/v1/users/me", json={"name": "Nope"}, headers=headers
    ).status_code == 404
