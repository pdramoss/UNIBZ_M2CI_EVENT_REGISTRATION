from unittest.mock import patch

import pytest

from web.app import APIClient, APIClientError, create_app


@pytest.fixture
def web_client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SESSION_FILE_DIR": str(tmp_path / "sessions"),
            "API_BASE_URL": "http://api.test",
        }
    )
    return app.test_client()


def test_login_keeps_bearer_token_out_of_browser_cookie(web_client):
    token = "server-side-access-token"
    initial_cookie = web_client.get("/login").headers["Set-Cookie"].split(";", 1)[0]
    with patch(
        "web.app.APIClient.request",
        return_value={
            "access_token": token,
            "token_type": "bearer",
            "role": "client",
        },
    ):
        response = web_client.post(
            "/login",
            data={"username": "alex", "password": "client-password"},
        )

    assert response.status_code == 302
    cookie = response.headers["Set-Cookie"]
    assert cookie.split(";", 1)[0] != initial_cookie
    assert token not in cookie
    with web_client.session_transaction() as browser_session:
        assert browser_session["access_token"] == token
        assert browser_session["role"] == "client"
        assert browser_session["username"] == "alex"


def test_client_can_create_registration_with_server_side_token(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "client-token"
        browser_session["role"] = "client"
        browser_session["username"] = "alex"

    with patch(
        "web.app.APIClient.request",
        autospec=True,
        return_value={"id": 8, "date": "2026-12-01", "user_id": 3, "event_id": 4},
    ) as api_request:
        response = web_client.post(
            "/registrations/new",
            data={"date": "2026-12-01", "event_id": "4"},
        )

    assert response.status_code == 302
    api_client = api_request.call_args.args[0]
    assert api_request.call_args.args[1:] == (
        "POST",
        "/api/v1/registrations",
        {"date": "2026-12-01", "event_id": "4"},
    )
    assert api_client.token == "client-token"


def test_registration_form_offers_events_as_a_dropdown(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "client-token"
        browser_session["role"] = "client"
        browser_session["username"] = "alex"

    events = [
        {"id": 4, "name": "Hackathon", "date": "2026-12-01"},
        {"id": 7, "name": "Workshop", "date": "2027-01-15"},
    ]
    with patch("web.app.APIClient.request", return_value=events):
        page = web_client.get("/registrations/new").get_data(as_text=True)

    assert '<select id="event_id" name="event_id"' in page
    assert '<option value="4" data-date="2026-12-01" >Hackathon' in page
    assert '<option value="7" data-date="2027-01-15" >Workshop' in page
    assert 'name="event_id" type="number"' not in page


def test_registration_form_shows_event_date_as_a_read_only_label(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "client-token"
        browser_session["role"] = "client"
        browser_session["username"] = "alex"

    events = [{"id": 4, "name": "Hackathon", "date": "2026-12-01"}]
    with patch("web.app.APIClient.request", return_value=events):
        page = web_client.get("/registrations/new").get_data(as_text=True)

    assert '<p class="field-value" id="date"' in page
    assert 'name="date"' not in page
    assert "registration_form.js" in page


def test_registration_date_is_taken_from_the_selected_event(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "client-token"
        browser_session["role"] = "client"
        browser_session["username"] = "alex"

    def api_response(_self, method, path, payload=None):
        if method == "GET" and path == "/api/v1/events/4":
            return {"id": 4, "name": "Hackathon", "date": "2026-12-01"}
        return {"id": 8, "date": "2026-12-01", "user_id": 3, "event_id": 4}

    with patch(
        "web.app.APIClient.request", autospec=True, side_effect=api_response
    ) as api_request:
        response = web_client.post(
            "/registrations/new",
            data={"event_id": "4", "date": "1999-01-01"},
        )

    assert response.status_code == 302
    assert api_request.call_args.args[1:] == (
        "POST",
        "/api/v1/registrations",
        {"event_id": "4", "date": "2026-12-01"},
    )


def test_administrator_can_create_another_administrator(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "admin-token"
        browser_session["role"] = "administrator"

    with patch(
        "web.app.APIClient.request",
        autospec=True,
        return_value={
            "id": 8,
            "name": "New Admin",
            "email": "new-admin@example.com",
            "age": 35,
            "username": "new-admin",
            "role": "administrator",
        },
    ) as api_request:
        response = web_client.post(
            "/accounts/new",
            data={
                "role": "administrator",
                "name": "New Admin",
                "email": "new-admin@example.com",
                "age": "35",
                "username": "new-admin",
                "password": "new-admin-password",
            },
        )

    assert response.status_code == 302
    api_client, method, path, payload = api_request.call_args.args
    assert api_client.token == "admin-token"
    assert method == "POST"
    assert path == "/api/v1/administrators"
    assert payload == {
        "name": "New Admin",
        "email": "new-admin@example.com",
        "age": "35",
        "username": "new-admin",
        "password": "new-admin-password",
    }


def test_role_gating_prevents_client_from_creating_events(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "client-token"
        browser_session["role"] = "client"

    with patch("web.app.APIClient.request", autospec=True) as api_request:
        response = web_client.post(
            "/events/new",
            data={
                "name": "Meetup",
                "date": "2026-12-01",
                "description": "A meetup",
                "capacity": "12",
                "place": "Bolzano",
            },
        )

    assert response.status_code == 403
    assert b"requires the administrator role" in response.data
    api_request.assert_not_called()


def test_administrator_event_delete_uses_bearer_token(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "admin-token"
        browser_session["role"] = "administrator"

    with patch("web.app.APIClient.request", autospec=True) as api_request:
        response = web_client.post("/events/7/delete")

    assert response.status_code == 302
    api_client, method, path, payload = api_request.call_args.args
    assert api_client.token == "admin-token"
    assert method == "DELETE"
    assert path == "/api/v1/events/7"
    assert payload is None


def test_event_list_renders_records_and_pagination(web_client):
    with patch(
        "web.app.APIClient.request",
        return_value=[
            {
                "id": 5,
                "name": "Meetup",
                "date": "2026-12-01",
                "description": "Community event",
                "capacity": 20,
                "place": "Bolzano",
            }
        ],
    ):
        response = web_client.get("/events?limit=1&offset=2")

    assert response.status_code == 200
    assert b"Meetup" in response.data
    assert b"Previous" in response.data
    assert b"Next" in response.data


def test_event_detail_shows_capacity_and_available_seats(web_client):
    with patch(
        "web.app.APIClient.request",
        return_value={
            "id": 5,
            "name": "Meetup",
            "date": "2026-12-01",
            "description": "Community event",
            "capacity": 20,
            "place": "Bolzano",
            "available_seats": 17,
        },
    ):
        page = web_client.get("/events/5").get_data(as_text=True)

    assert "<dt>Maximum capacity</dt><dd>20</dd>" in page
    assert "<dt>Available seats</dt><dd>17</dd>" in page


def test_api_validation_error_is_shown_without_echoing_password(web_client):
    with patch(
        "web.app.APIClient.request",
        side_effect=APIClientError("HTTP 422: Invalid account", 422),
    ):
        response = web_client.post(
            "/users/new",
            data={
                "name": "Alex",
                "email": "alex@example.com",
                "age": "30",
                "username": "alex",
                "password": "do-not-echo-this",
            },
        )

    assert response.status_code == 422
    assert b"HTTP 422: Invalid account" in response.data
    assert b"do-not-echo-this" not in response.data


def test_csrf_protects_browser_post_requests(tmp_path):
    app = create_app(
        {"TESTING": False, "SESSION_FILE_DIR": str(tmp_path / "sessions")}
    )

    response = app.test_client().post("/logout")

    assert response.status_code == 400


def test_logout_revokes_token_and_clears_server_side_session(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "client-token"
        browser_session["role"] = "client"

    with patch("web.app.APIClient.request", autospec=True) as api_request:
        response = web_client.post("/logout")

    assert response.status_code == 302
    assert api_request.call_args.args[0].token == "client-token"
    assert api_request.call_args.args[1:] == ("POST", "/api/v1/auth/logout")
    with web_client.session_transaction() as browser_session:
        assert "access_token" not in browser_session


def test_api_client_includes_bearer_header():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok": true}'

    with patch("web.app.urlopen", return_value=FakeResponse()) as urlopen:
        result = APIClient("http://api.test", token="opaque-token").request(
            "GET", "/api/v1/events"
        )

    api_request = urlopen.call_args.args[0]
    assert api_request.get_header("Authorization") == "Bearer opaque-token"
    assert result == {"ok": True}
