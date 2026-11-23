import os
from uuid import uuid4

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.e2e
def test_gateway_forwards_api_requests_unchanged():
    # Required, not defaulted: these tests have to skip rather than fail when no
    # stack is running, and credentials alone are often already in the shell.
    gateway_base_url = os.environ.get("GATEWAY_BASE_URL") or os.environ.get(
        "API_BASE_URL"
    )
    admin_username = os.environ.get("ADMIN_USERNAME")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not gateway_base_url or not admin_username or not admin_password:
        pytest.skip(
            "Set GATEWAY_BASE_URL (or API_BASE_URL), ADMIN_USERNAME, and "
            "ADMIN_PASSWORD to run gateway E2E tests"
        )

    event_name = f"Gateway E2E event {uuid4().hex}"
    event_id = None
    cleanup_errors: list[str] = []

    with sync_playwright() as playwright:
        gateway = playwright.request.new_context(base_url=gateway_base_url)
        try:
            health = gateway.get("/health")
            assert health.status == 200, health.text()
            assert health.json()["status"] == "ok"
            assert set(health.json()["services"]) == {
                "accounts",
                "events",
                "registrations",
                "web",
            }

            # An unauthenticated write must arrive as the API's own 401, not as a
            # gateway error, and must keep the challenge the UI depends on.
            rejected = gateway.post(
                "/api/v1/events",
                data={
                    "name": event_name,
                    "date": "2030-02-01",
                    "description": "Rejected without a token",
                    "capacity": 2,
                    "place": "Bolzano",
                },
            )
            assert rejected.status == 401, rejected.text()
            assert rejected.headers.get("www-authenticate") == "Bearer"

            login = gateway.post(
                "/api/v1/auth/login",
                data={"username": admin_username, "password": admin_password},
            )
            assert login.status == 200, login.text()
            admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            created = gateway.post(
                "/api/v1/events",
                data={
                    "name": event_name,
                    "date": "2030-02-01",
                    "description": "Created through the gateway",
                    "capacity": 2,
                    "place": "Bolzano",
                },
                headers=admin_headers,
            )
            assert created.status == 201, created.text()
            event_id = created.json()["id"]
            assert created.json()["available_seats"] == 2

            read_back = gateway.get(f"/api/v1/events/{event_id}")
            assert read_back.status == 200, read_back.text()
            assert read_back.json()["name"] == event_name

            # The query string has to survive the hop: the UI's event dropdown
            # asks for limit=500, so a dropped query would silently truncate it.
            limited = gateway.get("/api/v1/events?limit=1&offset=0")
            assert limited.status == 200, limited.text()
            assert len(limited.json()) == 1

            # One URL covers the interface and all three backend services, so
            # nothing outside the gateway needs to know how the back end is
            # divided.
            page = gateway.get("/")
            assert page.status == 200, page.text()
            assert "text/html" in page.headers["content-type"]
            assert "text/html" not in limited.headers["content-type"]

            # Each service publishes its own OpenAPI document through the same
            # URL, and the three are disjoint: that is the split, observable from
            # outside.
            documented = {}
            for service in ("accounts", "events", "registrations"):
                page = gateway.get(f"/docs/{service}")
                assert page.status == 200, page.text()
                document = gateway.get(f"/docs/{service}/openapi.json")
                assert document.status == 200, document.text()
                documented[service] = set(document.json()["paths"])

            assert "/api/v1/auth/login" in documented["accounts"]
            assert documented["events"] == {
                "/api/v1/events",
                "/api/v1/events/{event_id}",
            }
            assert documented["registrations"] == {
                "/api/v1/registrations",
                "/api/v1/registrations/{registration_id}",
            }
            for left, right in (
                ("accounts", "events"),
                ("accounts", "registrations"),
                ("events", "registrations"),
            ):
                assert not documented[left] & documented[right], (left, right)

            # An /api/v1 path no service owns is the gateway's own answer, in the
            # API's error shape rather than the interface's HTML.
            unowned = gateway.get("/api/v1/nothing")
            assert unowned.status == 404, unowned.text()
            assert "detail" in unowned.json()

            missing = gateway.get("/api/v1/events/99999999")
            assert missing.status == 404, missing.text()
            assert "detail" in missing.json()

            spanish = gateway.get(
                "/api/v1/events/99999999", headers={"Accept-Language": "es"}
            )
            assert spanish.status == 404
            assert spanish.json()["detail"] != missing.json()["detail"]

            logout = gateway.post("/api/v1/auth/logout", headers=admin_headers)
            assert logout.status == 204, logout.text()
        finally:
            if event_id is not None:
                relogin = gateway.post(
                    "/api/v1/auth/login",
                    data={"username": admin_username, "password": admin_password},
                )
                if relogin.status != 200:
                    cleanup_errors.append(
                        f"cleanup login: expected HTTP 200, got {relogin.status}"
                    )
                else:
                    headers = {
                        "Authorization": f"Bearer {relogin.json()['access_token']}"
                    }
                    deleted = gateway.delete(
                        f"/api/v1/events/{event_id}", headers=headers
                    )
                    if deleted.status != 204:
                        cleanup_errors.append(
                            "delete test event: expected HTTP 204, got "
                            f"{deleted.status}: {deleted.text()}"
                        )
                    gateway.post("/api/v1/auth/logout", headers=headers)
            gateway.dispose()

    assert not cleanup_errors, "; ".join(cleanup_errors)
