"""The registrations service: ownership, capacity and client-only access."""

from tests.unit.conftest import ServiceRouter, bearer_headers, create_user, login


def test_localized_authentication_error_preserves_status_and_headers(
    api: ServiceRouter,
):
    response = api.get(
        "/api/v1/registrations", headers={"Accept-Language": "es"}
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": "Se requiere autenticación con un token Bearer"
    }


def test_registration_rejects_missing_event(api: ServiceRouter):
    create_user(api)
    client_headers = bearer_headers(login(api, "alex", "test-password"))
    response = api.post(
        "/api/v1/registrations",
        json={"date": "2026-11-11", "event_id": 404},
        headers=client_headers,
    )
    assert response.status_code == 404


def test_registration_crud_requires_client_and_enforces_ownership(api: ServiceRouter):
    first_user = create_user(api, "alex")
    second_user = create_user(api, "sam")
    first_client_headers = bearer_headers(login(api, "alex", "test-password"))
    second_client_headers = bearer_headers(login(api, "sam", "test-password"))
    admin_headers = bearer_headers(login(api, "test-admin", "test-admin-password"))
    event = api.post(
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

    unauthenticated = api.get("/api/v1/registrations")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"
    invalid_password = api.get(
        "/api/v1/registrations", headers=bearer_headers("invalid-token")
    )
    assert invalid_password.status_code == 401

    registration_response = api.post(
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
        response = getattr(api, method)(
            url, headers=second_client_headers, **kwargs
        )
        if method == "get" and url.endswith("/registrations"):
            assert response.status_code == 200
            assert response.json() == []
        else:
            assert response.status_code == 404

    assert api.get(
        "/api/v1/registrations", headers=first_client_headers
    ).json() == [registration]
    changed_owner = api.patch(
        f"/api/v1/registrations/{registration['id']}",
        json={"user_id": second_user["id"]},
        headers=first_client_headers,
    )
    assert changed_owner.status_code == 422
    assert api.get(
        f"/api/v1/registrations/{registration['id']}",
        headers=first_client_headers,
    ).json() == registration
