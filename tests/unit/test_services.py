"""The backend is three independently deployed services over one database.

These tests pin the two properties that split depends on: each service serves
only the routes it owns, and a session issued by one is honoured by the others
because they all read the same auth_sessions table.

Since each service is now built and imaged on its own, nothing composes them
together any more -- so the coverage check below compares the union of what the
three actually serve against the API the gateway expects to be able to route.
"""

import pytest

from tests.unit.conftest import SERVICE_APPS

EXPECTED_ROUTES = {
    "accounts": {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/users",
        "/api/v1/users/me",
        "/api/v1/users/{user_id}",
        "/api/v1/clients",
        "/api/v1/administrators",
    },
    "events": {
        "/api/v1/events",
        "/api/v1/events/{event_id}",
    },
    "registrations": {
        "/api/v1/registrations",
        "/api/v1/registrations/{registration_id}",
    },
}


def api_paths(app) -> set[str]:
    # Read the app's own OpenAPI document rather than walking app.routes: FastAPI
    # keeps an included router nested instead of flattening its routes, and this
    # is the surface a client actually sees.
    return set(app.openapi()["paths"])


@pytest.mark.parametrize("name", sorted(EXPECTED_ROUTES))
def test_each_service_serves_only_its_own_routes(name):
    assert api_paths(SERVICE_APPS[name]) == EXPECTED_ROUTES[name]


def test_the_services_together_cover_the_whole_api():
    # No service may be left holding a route no other serves, and no route may
    # be served twice: the gateway routes each path to exactly one upstream.
    served = [api_paths(app) for app in SERVICE_APPS.values()]
    union = set().union(*served)

    assert union == set().union(*EXPECTED_ROUTES.values())
    assert sum(len(paths) for paths in served) == len(union), "a path is served twice"


@pytest.mark.parametrize("name", sorted(EXPECTED_ROUTES))
def test_a_service_does_not_answer_another_services_paths(services, name):
    foreign = set().union(*EXPECTED_ROUTES.values()) - EXPECTED_ROUTES[name]
    for path in sorted(foreign):
        if "{" in path:
            continue
        response = services[name].get(path)
        assert response.status_code == 404, f"{name} answered {path}"


@pytest.mark.parametrize("name", sorted(EXPECTED_ROUTES))
def test_each_service_documents_itself_under_its_own_path(services, name):
    # The gateway routes /docs/<name> to this service, so the Swagger page and
    # the document it fetches have to live under that prefix. The Compose
    # healthcheck polls the document, so this is a contract.
    assert services[name].get(f"/docs/{name}").status_code == 200
    document = services[name].get(f"/docs/{name}/openapi.json")
    assert document.status_code == 200
    assert set(document.json()["paths"]) == EXPECTED_ROUTES[name]
    # No service serves a combined documentation path; there is no combined app.
    assert services[name].get("/openapi.json").status_code == 404
    assert services[name].get("/docs").status_code == 404


def test_a_session_from_accounts_is_honoured_by_the_other_services(services):
    accounts, events, registrations = (
        services["accounts"],
        services["events"],
        services["registrations"],
    )

    admin_login = accounts.post(
        "/api/v1/auth/login",
        json={"username": "test-admin", "password": "test-admin-password"},
    )
    assert admin_login.status_code == 200, admin_login.text
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    # The administrator session was issued by accounts and is spent on events.
    created = events.post(
        "/api/v1/events",
        json={
            "name": "Split backend",
            "date": "2026-12-01",
            "description": "One database, three services",
            "capacity": 1,
            "place": "Bolzano",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    signup = accounts.post(
        "/api/v1/users",
        json={
            "name": "Alex",
            "password": "test-password",
            "email": "alex@example.com",
            "age": 30,
            "username": "alex",
        },
    )
    assert signup.status_code == 201, signup.text
    client_login = accounts.post(
        "/api/v1/auth/login",
        json={"username": "alex", "password": "test-password"},
    )
    client_headers = {"Authorization": f"Bearer {client_login.json()['access_token']}"}

    # registrations validates the client's session, and resolves the event and
    # its capacity, entirely through the shared database.
    booked = registrations.post(
        "/api/v1/registrations",
        json={"date": "2026-12-01", "event_id": event_id},
        headers=client_headers,
    )
    assert booked.status_code == 201, booked.text

    # The capacity check still sees the event it does not own.
    assert events.get(f"/api/v1/events/{event_id}").json()["available_seats"] == 0

    # Logging out through accounts revokes the session the other services accept.
    assert accounts.post("/api/v1/auth/logout", headers=client_headers).status_code == 204
    rejected = registrations.get("/api/v1/registrations", headers=client_headers)
    assert rejected.status_code == 401
