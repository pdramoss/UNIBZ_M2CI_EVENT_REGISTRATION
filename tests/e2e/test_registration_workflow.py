import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from playwright.sync_api import APIRequestContext, APIResponse, sync_playwright


@dataclass
class RegistrationWorkflow:
    api: APIRequestContext
    admin_headers: dict[str, str] | None = None
    client_headers: dict[str, str] | None = None
    event_id: int | None = None
    user_id: int | None = None
    registration_id: int | None = None


def _record_status(
    errors: list[str], response: APIResponse, expected_status: int, operation: str
) -> None:
    if response.status != expected_status:
        errors.append(
            f"{operation}: expected HTTP {expected_status}, "
            f"got {response.status}: {response.text()}"
        )


@pytest.fixture
def registration_workflow(
    request: pytest.FixtureRequest,
) -> Iterator[RegistrationWorkflow]:
    base_url = os.environ.get("API_BASE_URL")
    admin_username = os.environ.get("ADMIN_USERNAME")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not base_url or not admin_username or not admin_password:
        pytest.skip(
            "Set API_BASE_URL, ADMIN_USERNAME, and ADMIN_PASSWORD to run API E2E tests"
        )

    with sync_playwright() as playwright:
        api = playwright.request.new_context(base_url=base_url)
        workflow = RegistrationWorkflow(api=api)
        yield workflow

        cleanup_errors: list[str] = []
        if workflow.registration_id is not None and workflow.client_headers:
            response = api.delete(
                f"/api/v1/registrations/{workflow.registration_id}",
                headers=workflow.client_headers,
            )
            _record_status(cleanup_errors, response, 204, "delete test registration")
            response = api.get(
                f"/api/v1/registrations/{workflow.registration_id}",
                headers=workflow.client_headers,
            )
            _record_status(
                cleanup_errors, response, 404, "verify registration cleanup"
            )

        if workflow.client_headers:
            response = api.post(
                "/api/v1/auth/logout", headers=workflow.client_headers
            )
            _record_status(cleanup_errors, response, 204, "revoke Client session")
            response = api.get(
                "/api/v1/registrations", headers=workflow.client_headers
            )
            _record_status(
                cleanup_errors, response, 401, "verify Client session revocation"
            )

        if workflow.user_id is not None:
            response = api.delete(f"/api/v1/users/{workflow.user_id}")
            _record_status(cleanup_errors, response, 204, "delete test Client")
            response = api.get(f"/api/v1/users/{workflow.user_id}")
            _record_status(cleanup_errors, response, 404, "verify Client cleanup")

        if workflow.event_id is not None and workflow.admin_headers:
            response = api.delete(
                f"/api/v1/events/{workflow.event_id}",
                headers=workflow.admin_headers,
            )
            _record_status(cleanup_errors, response, 204, "delete test event")
            response = api.get(f"/api/v1/events/{workflow.event_id}")
            _record_status(cleanup_errors, response, 404, "verify event cleanup")

        if workflow.admin_headers:
            response = api.post(
                "/api/v1/auth/logout", headers=workflow.admin_headers
            )
            _record_status(cleanup_errors, response, 204, "revoke Administrator session")
            response = api.delete(
                "/api/v1/events/0", headers=workflow.admin_headers
            )
            _record_status(
                cleanup_errors, response, 401, "verify Administrator session revocation"
            )

        api.dispose()
        if cleanup_errors:
            pytest.fail("E2E cleanup failed:\n" + "\n".join(cleanup_errors))


@pytest.mark.e2e
def test_client_can_register_for_an_event(registration_workflow: RegistrationWorkflow):
    api = registration_workflow.api
    unique_id = uuid4().hex
    event_payload = {
        "name": f"Playwright E2E event {unique_id}",
        "date": "2030-01-01",
        "description": "Event created by the Playwright API workflow",
        "capacity": 1,
        "place": "Bolzano",
    }

    admin_login = api.post(
        "/api/v1/auth/login",
        data={
            "username": os.environ["ADMIN_USERNAME"],
            "password": os.environ["ADMIN_PASSWORD"],
        },
    )
    assert admin_login.status == 200, admin_login.text()
    admin_token = admin_login.json()["access_token"]
    registration_workflow.admin_headers = {
        "Authorization": f"Bearer {admin_token}"
    }
    assert admin_login.json()["role"] == "administrator"

    event_response = api.post(
        "/api/v1/events",
        data=event_payload,
        headers=registration_workflow.admin_headers,
    )
    assert event_response.status == 201, event_response.text()
    event = event_response.json()
    registration_workflow.event_id = event["id"]
    assert {key: event[key] for key in event_payload} == event_payload

    event_state = api.get(f"/api/v1/events/{event['id']}")
    assert event_state.status == 200, event_state.text()
    assert event_state.json() == event

    client_payload = {
        "name": "Playwright E2E Client",
        "password": f"Test-{unique_id}",
        "email": f"playwright-{unique_id}@example.com",
        "age": 30,
        "username": f"pw-{unique_id}",
    }
    client_response = api.post("/api/v1/users", data=client_payload)
    assert client_response.status == 201, client_response.text()
    client = client_response.json()
    registration_workflow.user_id = client["id"]
    assert client["role"] == "client"
    assert "password" not in client
    client_state = api.get(f"/api/v1/users/{client['id']}")
    assert client_state.status == 200, client_state.text()
    assert client_state.json() == client

    client_login = api.post(
        "/api/v1/auth/login",
        data={
            "username": client_payload["username"],
            "password": client_payload["password"],
        },
    )
    assert client_login.status == 200, client_login.text()
    client_token = client_login.json()["access_token"]
    registration_workflow.client_headers = {
        "Authorization": f"Bearer {client_token}"
    }
    assert client_login.json()["role"] == "client"

    registration_payload = {
        "date": "2026-11-11",
        "event_id": registration_workflow.event_id,
    }
    create_response = api.post(
        "/api/v1/registrations",
        data=registration_payload,
        headers=registration_workflow.client_headers,
    )
    assert create_response.status == 201, create_response.text()
    registration = create_response.json()
    registration_workflow.registration_id = registration["id"]
    expected_registration = {
        "id": registration["id"],
        "date": registration_payload["date"],
        "user_id": client["id"],
        "event_id": event["id"],
    }
    assert registration == expected_registration

    read_response = api.get(
        f"/api/v1/registrations/{registration['id']}",
        headers=registration_workflow.client_headers,
    )
    assert read_response.status == 200, read_response.text()
    assert read_response.json() == expected_registration

    list_response = api.get(
        "/api/v1/registrations",
        headers=registration_workflow.client_headers,
    )
    assert list_response.status == 200, list_response.text()
    assert list_response.json() == [expected_registration]
