import os
import re
from uuid import uuid4

import pytest
from playwright.sync_api import APIResponse, Error as PlaywrightError, sync_playwright


def _csrf_token(response: APIResponse) -> str:
    match = re.search(
        r'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"', response.text()
    )
    assert match is not None, "The page did not include a CSRF token"
    return match.group(1)


def _check_status(
    errors: list[str], response: APIResponse, expected: int, operation: str
) -> None:
    if response.status != expected:
        errors.append(
            f"{operation}: expected HTTP {expected}, got "
            f"{response.status}: {response.text()}"
        )


@pytest.mark.e2e
def test_client_manages_registration_through_web_forms():
    api_base_url = os.environ.get("API_BASE_URL")
    web_base_url = os.environ.get("WEB_BASE_URL", "http://127.0.0.1:5000")
    admin_username = os.environ.get("ADMIN_USERNAME")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not api_base_url or not admin_username or not admin_password:
        pytest.skip(
            "Set API_BASE_URL, ADMIN_USERNAME, and ADMIN_PASSWORD to run web E2E tests"
        )

    unique_id = uuid4().hex
    username = f"web-{unique_id}"
    password = f"Test-{unique_id}"
    event_name = f"Web E2E event {unique_id}"
    user_id = None
    event_id = None
    registration_id = None
    admin_headers = None
    client_headers = None
    cleanup_errors: list[str] = []

    with sync_playwright() as playwright:
        api = playwright.request.new_context(base_url=api_base_url)
        web = playwright.request.new_context(base_url=web_base_url)
        try:
            admin_login = api.post(
                "/api/v1/auth/login",
                data={"username": admin_username, "password": admin_password},
            )
            assert admin_login.status == 200, admin_login.text()
            admin_token = admin_login.json()["access_token"]
            admin_headers = {
                "Authorization": f"Bearer {admin_token}"
            }

            login_page = web.get("/login")
            login_response = web.post(
                "/login",
                form={
                    "csrf_token": _csrf_token(login_page),
                    "username": admin_username,
                    "password": admin_password,
                },
            )
            assert login_response.status == 200, login_response.text()
            assert admin_token not in login_response.headers.get("set-cookie", "")

            event_form = web.get("/events/new")
            event_response = web.post(
                "/events/new",
                form={
                    "csrf_token": _csrf_token(event_form),
                    "name": event_name,
                    "date": "2030-01-01",
                    "description": "Created by the web UI workflow",
                    "capacity": "1",
                    "place": "Bolzano",
                },
            )
            assert event_response.status == 200, event_response.text()
            assert event_name in event_response.text()
            event_id = int(event_response.url.rsplit("/", 1)[1])
            event_edit_page = web.get(f"/events/{event_id}/edit")
            event_edit = web.post(
                f"/events/{event_id}/edit",
                form={
                    "csrf_token": _csrf_token(event_edit_page),
                    "name": event_name,
                    "date": "2030-01-01",
                    "description": "Updated by the web UI workflow",
                    "capacity": "1",
                    "place": "Merano",
                },
            )
            assert event_edit.status == 200, event_edit.text()
            assert "Merano" in event_edit.text()
            assert api.get(f"/api/v1/events/{event_id}").json()["place"] == "Merano"

            user_form = web.get("/users/new")
            user_response = web.post(
                "/users/new",
                form={
                    "csrf_token": _csrf_token(user_form),
                    "name": "Web E2E Client",
                    "email": f"{username}@example.com",
                    "age": "30",
                    "username": username,
                    "password": password,
                },
            )
            assert user_response.status == 200, user_response.text()
            assert username in user_response.text()
            user_id = int(user_response.url.rsplit("/", 1)[1])
            assert api.get(f"/api/v1/users/{user_id}").status == 200
            user_edit_page = web.get(f"/users/{user_id}/edit")
            user_edit = web.post(
                f"/users/{user_id}/edit",
                form={
                    "csrf_token": _csrf_token(user_edit_page),
                    "name": "Web E2E Client",
                    "email": f"{username}@example.com",
                    "age": "31",
                    "username": username,
                    "password": "",
                },
            )
            assert user_edit.status == 200, user_edit.text()
            assert "31" in user_edit.text()
            assert api.get(f"/api/v1/users/{user_id}").json()["age"] == 31

            client_login = api.post(
                "/api/v1/auth/login",
                data={"username": username, "password": password},
            )
            assert client_login.status == 200, client_login.text()
            client_headers = {
                "Authorization": f"Bearer {client_login.json()['access_token']}"
            }

            home_page = web.get("/")
            admin_logout = web.post(
                "/logout", form={"csrf_token": _csrf_token(home_page)}
            )
            assert admin_logout.status == 200, admin_logout.text()

            client_login_page = web.get("/login")
            client_web_login = web.post(
                "/login",
                form={
                    "csrf_token": _csrf_token(client_login_page),
                    "username": username,
                    "password": password,
                },
            )
            assert client_web_login.status == 200, client_web_login.text()
            assert "My registrations" in client_web_login.text()

            registration_form = web.get("/registrations/new")
            create_registration = web.post(
                "/registrations/new",
                form={
                    "csrf_token": _csrf_token(registration_form),
                    "date": "2030-01-02",
                    "event_id": str(event_id),
                },
            )
            assert create_registration.status == 200, create_registration.text()
            registration_id = int(create_registration.url.rsplit("/", 1)[1])
            assert str(event_id) in create_registration.text()
            registration_edit_page = web.get(
                f"/registrations/{registration_id}/edit"
            )
            registration_edit = web.post(
                f"/registrations/{registration_id}/edit",
                form={
                    "csrf_token": _csrf_token(registration_edit_page),
                    "date": "2030-01-03",
                    "event_id": str(event_id),
                },
            )
            assert registration_edit.status == 200, registration_edit.text()

            registrations_page = web.get("/registrations")
            assert str(registration_id) in registrations_page.text()
            registration_state = api.get(
                f"/api/v1/registrations/{registration_id}",
                headers=client_headers,
            )
            assert registration_state.status == 200, registration_state.text()
            assert registration_state.json() == {
                "id": registration_id,
                "date": "2030-01-03",
                "user_id": user_id,
                "event_id": event_id,
            }

            detail_page = web.get(f"/registrations/{registration_id}")
            delete_response = web.post(
                f"/registrations/{registration_id}/delete",
                form={"csrf_token": _csrf_token(detail_page)},
            )
            assert delete_response.status == 200, delete_response.text()
            registration_id = None
            assert (
                f'href="/registrations/{registration_state.json()["id"]}"'
                not in web.get("/registrations").text()
            )
            assert api.get(
                f"/api/v1/registrations/{registration_state.json()['id']}",
                headers=client_headers,
            ).status == 404

            client_logout = api.post(
                "/api/v1/auth/logout", headers=client_headers
            )
            assert client_logout.status == 204, client_logout.text()
            client_headers = None

            user_detail = web.get(f"/users/{user_id}")
            user_delete = web.post(
                f"/users/{user_id}/delete",
                form={"csrf_token": _csrf_token(user_detail)},
            )
            assert user_delete.status == 200, user_delete.text()
            assert (
                api.get(f"/api/v1/users/{user_id}").status == 404
            )
            user_id = None

            client_home = web.get("/")
            client_web_logout = web.post(
                "/logout", form={"csrf_token": _csrf_token(client_home)}
            )
            assert client_web_logout.status == 200, client_web_logout.text()
            admin_login_page = web.get("/login")
            admin_web_login = web.post(
                "/login",
                form={
                    "csrf_token": _csrf_token(admin_login_page),
                    "username": admin_username,
                    "password": admin_password,
                },
            )
            assert admin_web_login.status == 200, admin_web_login.text()
            event_detail = web.get(f"/events/{event_id}")
            event_delete = web.post(
                f"/events/{event_id}/delete",
                form={"csrf_token": _csrf_token(event_detail)},
            )
            assert event_delete.status == 200, event_delete.text()
            assert "Event deleted." in event_delete.text(), event_delete.text()
            assert api.get(f"/api/v1/events/{event_id}").status == 404
            event_id = None

        finally:
            try:
                home_page = web.get("/")
                web.post("/logout", form={"csrf_token": _csrf_token(home_page)})
            except (AssertionError, PlaywrightError) as error:
                cleanup_errors.append(f"log out web session: {error}")

            if registration_id is not None and client_headers:
                response = api.delete(
                    f"/api/v1/registrations/{registration_id}",
                    headers=client_headers,
                )
                _check_status(
                    cleanup_errors, response, 204, "delete test registration"
                )
                response = api.get(
                    f"/api/v1/registrations/{registration_id}",
                    headers=client_headers,
                )
                _check_status(
                    cleanup_errors, response, 404, "verify registration cleanup"
                )

            if client_headers:
                response = api.post(
                    "/api/v1/auth/logout", headers=client_headers
                )
                _check_status(cleanup_errors, response, 204, "revoke Client session")
                response = api.get(
                    "/api/v1/registrations", headers=client_headers
                )
                _check_status(
                    cleanup_errors, response, 401, "verify Client session revocation"
                )

            if user_id is not None:
                response = api.delete(f"/api/v1/users/{user_id}")
                _check_status(cleanup_errors, response, 204, "delete test Client")
                response = api.get(f"/api/v1/users/{user_id}")
                _check_status(cleanup_errors, response, 404, "verify Client cleanup")

            if event_id is not None and admin_headers:
                response = api.delete(
                    f"/api/v1/events/{event_id}", headers=admin_headers
                )
                _check_status(cleanup_errors, response, 204, "delete test event")
                response = api.get(f"/api/v1/events/{event_id}")
                _check_status(cleanup_errors, response, 404, "verify event cleanup")

            if admin_headers:
                response = api.post("/api/v1/auth/logout", headers=admin_headers)
                _check_status(
                    cleanup_errors, response, 204, "revoke Administrator session"
                )
                response = api.delete("/api/v1/events/0", headers=admin_headers)
                _check_status(
                    cleanup_errors,
                    response,
                    401,
                    "verify Administrator session revocation",
                )

            api.dispose()
            web.dispose()
            if cleanup_errors:
                pytest.fail("Web E2E cleanup failed:\n" + "\n".join(cleanup_errors))
