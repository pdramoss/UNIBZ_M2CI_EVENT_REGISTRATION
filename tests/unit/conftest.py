"""Shared fixtures for the unit suite.

There is no all-in-one application any more: each service is built, imaged and
deployed on its own. The suite therefore runs the three of them side by side in
one interpreter, over one temporary SQLite file, which is exactly how they run in
Compose.

Most tests do not care which service answers; they care that the API behaves.
For those, ``api`` dispatches each request to the service that owns its path,
using the same prefix table the gateway routes by. A test that wants a specific
service still gets the clients themselves through ``services``.
"""

from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from services.accounts.main import app as accounts_app
from services.events.main import app as events_app
from services.registrations.main import app as registrations_app

SERVICE_APPS = {
    "accounts": accounts_app,
    "events": events_app,
    "registrations": registrations_app,
}

# The same ownership the gateway encodes in its location blocks. Longest match
# is unnecessary here because no prefix is a prefix of another.
SERVICE_FOR_PREFIX = (
    ("/api/v1/auth", "accounts"),
    ("/api/v1/users", "accounts"),
    ("/api/v1/clients", "accounts"),
    ("/api/v1/administrators", "accounts"),
    ("/api/v1/events", "events"),
    ("/api/v1/registrations", "registrations"),
)


class ServiceRouter:
    """Sends each request to the service that owns the path, like the gateway.

    Using this instead of one combined app means a test that expects a 404 gets
    it from the owning service, not from a service that simply never had the
    route -- so the suite keeps testing behaviour rather than composition.
    """

    def __init__(self, clients: dict[str, TestClient]) -> None:
        self._clients = clients

    def client_for(self, path: str) -> TestClient:
        for prefix, name in SERVICE_FOR_PREFIX:
            if path == prefix or path.startswith(f"{prefix}/"):
                return self._clients[name]
        raise AssertionError(
            f"No service owns {path!r}; the gateway would answer its own 404."
        )

    def get(self, path: str, **kwargs):
        return self.client_for(path).get(path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.client_for(path).post(path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.client_for(path).patch(path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.client_for(path).put(path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.client_for(path).delete(path, **kwargs)


@pytest.fixture
def service_environment(tmp_path, monkeypatch):
    """Point every service at one temporary database and a known bootstrap admin."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")
    return tmp_path / "test.sqlite3"


@pytest.fixture
def services(service_environment):
    """A live TestClient per service, all sharing one database."""
    with ExitStack() as stack:
        yield {
            name: stack.enter_context(TestClient(app))
            for name, app in SERVICE_APPS.items()
        }


@pytest.fixture
def api(services):
    """The whole API, routed to the owning service per request."""
    return ServiceRouter(services)


def create_user(api: ServiceRouter, username: str = "alex") -> dict:
    response = api.post(
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


def login(api: ServiceRouter, username: str, password: str) -> str:
    response = api.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
