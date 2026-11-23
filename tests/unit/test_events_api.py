"""The events service: the catalogue, its authorization and its seat counts."""

from datetime import date

from tests.unit.conftest import ServiceRouter, bearer_headers, create_user, login


def test_event_writes_require_administrator(api: ServiceRouter, monkeypatch):
    admin_headers = bearer_headers(login(api, "test-admin", "test-admin-password"))
    event_payload = {
        "name": "Private meetup",
        "date": "2026-12-01",
        "description": "Admin-only creation",
        "capacity": 10,
        "place": "Bolzano",
    }

    unauthorized = api.post("/api/v1/events", json=event_payload)
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"

    invalid_credentials = api.post(
        "/api/v1/auth/login",
        json={"username": "wrong-admin", "password": "wrong-password"},
    )
    assert invalid_credentials.status_code == 401

    created = api.post(
        "/api/v1/events",
        json=event_payload,
        headers=admin_headers,
    )
    assert created.status_code == 201
    event_id = created.json()["id"]

    unauthorized_update = api.patch(
        f"/api/v1/events/{event_id}", json={"name": "Changed"}
    )
    assert unauthorized_update.status_code == 401
    unauthorized_delete = api.delete(f"/api/v1/events/{event_id}")
    assert unauthorized_delete.status_code == 401

    monkeypatch.delenv("ADMIN_USERNAME")
    monkeypatch.delenv("ADMIN_PASSWORD")
    unavailable_admin = api.post("/api/v1/events", json=event_payload)
    assert unavailable_admin.status_code == 401
    bootstrap_session_still_valid = api.post(
        "/api/v1/events", json=event_payload, headers=admin_headers
    )
    assert bootstrap_session_still_valid.status_code == 201


def test_event_and_registration_crud_enforces_capacity(api: ServiceRouter):
    user = create_user(api)
    admin_headers = bearer_headers(login(api, "test-admin", "test-admin-password"))
    client_headers = bearer_headers(login(api, "alex", "test-password"))
    event_response = api.post(
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
    assert api.get(f"/api/v1/events/{event_id}").json() == event
    assert api.get("/api/v1/events").json() == [event]

    updated_event = api.patch(
        f"/api/v1/events/{event_id}",
        json={"place": "Merano"},
        headers=admin_headers,
    )
    assert updated_event.status_code == 200
    assert updated_event.json()["place"] == "Merano"

    registration_response = api.post(
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
        api.get(
            f"/api/v1/registrations/{registration['id']}",
            headers=client_headers,
        ).json()
        == registration
    )
    assert api.get(
        "/api/v1/registrations", headers=client_headers
    ).json() == [registration]

    create_user(api, "sam")
    second_client_headers = bearer_headers(login(api, "sam", "test-password"))
    full_event = api.post(
        "/api/v1/registrations",
        json={
            "date": "2026-11-12",
            "event_id": event_id,
        },
        headers=second_client_headers,
    )
    assert full_event.status_code == 409

    updated = api.patch(
        f"/api/v1/registrations/{registration['id']}",
        json={"date": "2026-11-13"},
        headers=client_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["date"] == "2026-11-13"

    reduce_capacity = api.patch(
        f"/api/v1/events/{event_id}",
        json={"capacity": 0},
        headers=admin_headers,
    )
    assert reduce_capacity.status_code == 409

    assert (
        api.delete(
            f"/api/v1/registrations/{registration['id']}",
            headers=client_headers,
        ).status_code
        == 204
    )
    assert (
        api.get(
            f"/api/v1/registrations/{registration['id']}",
            headers=client_headers,
        ).status_code
        == 404
    )

    cascade_registration = api.post(
        "/api/v1/registrations",
        json={
            "date": "2026-11-14",
            "event_id": event_id,
        },
        headers=client_headers,
    )
    assert cascade_registration.status_code == 201
    assert (
        api.delete(
            f"/api/v1/events/{event_id}",
            headers=admin_headers,
        ).status_code
        == 204
    )
    assert (
        api.get(
            f"/api/v1/registrations/{cascade_registration.json()['id']}",
            headers=client_headers,
        ).status_code
        == 404
    )


def test_event_reports_available_seats(api: ServiceRouter):
    create_user(api, "alex")
    admin_headers = bearer_headers(login(api, "test-admin", "test-admin-password"))
    client_headers = bearer_headers(login(api, "alex", "test-password"))
    event = api.post(
        "/api/v1/events",
        json={
            "name": "Workshop",
            "date": "2026-12-01",
            "description": "Two seats only",
            "capacity": 2,
            "place": "Bolzano",
        },
        headers=admin_headers,
    ).json()
    assert event["capacity"] == 2
    assert event["available_seats"] == 2

    registration = api.post(
        "/api/v1/registrations",
        json={"date": "2026-12-01", "event_id": event["id"]},
        headers=client_headers,
    )
    assert registration.status_code == 201

    detail = api.get(f"/api/v1/events/{event['id']}").json()
    assert detail["capacity"] == 2
    assert detail["available_seats"] == 1
    assert api.get("/api/v1/events").json()[0]["available_seats"] == 1

    assert (
        api.delete(
            f"/api/v1/registrations/{registration.json()['id']}",
            headers=client_headers,
        ).status_code
        == 204
    )
    assert api.get(f"/api/v1/events/{event['id']}").json()["available_seats"] == 2
