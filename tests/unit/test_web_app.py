from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from web.app import APIClient, APIClientError, create_app


@pytest.fixture
def web_client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SESSION_FILE_DIR": str(tmp_path / "sessions"),
            "GATEWAY_URL": "http://gateway.test",
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
        side_effect=APIClientError(
            "Invalid account.", 422, field_errors={"email": "Not a valid email."}
        ),
    ):
        response = web_client.post(
            "/users/new",
            data={
                "name": "Alex",
                "email": "nope",
                "age": "30",
                "username": "alex",
                "password": "do-not-echo-this",
            },
        )

    page = response.get_data(as_text=True)
    assert response.status_code == 422
    assert "Invalid account." in page
    assert "HTTP 422" not in page
    assert "do-not-echo-this" not in page
    # The summary links to the field, and the field carries the message itself.
    assert '<a href="#email">Not a valid email.</a>' in page
    assert 'aria-describedby="email-error"' in page
    assert '<p class="field-error" id="email-error">' in page


def test_api_error_text_is_human_and_keeps_the_localized_detail():
    """A 422 payload is unpacked per field; a localized detail is kept verbatim."""

    def fail(status, body):
        error = HTTPError("http://api.test", status, "err", {}, None)
        error.read = lambda: body
        with patch("web.app.urlopen", side_effect=error):
            with pytest.raises(APIClientError) as raised:
                APIClient("http://api.test").request("GET", "/api/v1/events")
        return raised.value

    unprocessable = fail(
        422,
        b'{"detail": [{"type": "missing", "loc": ["body", "email"],'
        b' "msg": "field required"}]}',
    )
    assert unprocessable.status_code == 422
    assert unprocessable.field_errors == {"email": "Field required."}
    assert "loc" not in str(unprocessable)
    assert str(unprocessable) == "Some of the details need correcting."

    # common/messages.py already translated this one for the Accept-Language.
    localized = fail(409, b'{"detail": "Email or username already exists"}')
    assert str(localized) == "Email or username already exists."
    assert localized.field_errors == {}

    opaque = fail(503, b"")
    assert str(opaque) == "The service is unavailable right now. Try again in a moment."


def test_delete_asks_for_confirmation_before_calling_the_api(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "admin-token"
        browser_session["role"] = "administrator"

    with patch(
        "web.app.APIClient.request",
        return_value={"id": 7, "name": "Jazz Night", "capacity": 20},
    ) as api_request:
        page = web_client.get("/events/7/delete").get_data(as_text=True)

    # Nothing was deleted: the only call made was the read that names the record.
    assert [call.args[0] for call in api_request.call_args_list] == ["GET"]
    assert "Delete Jazz Night?" in page
    assert "cannot be undone" in page
    assert "Keep event" in page
    assert 'action="/events/7/delete"' in page


def test_unknown_resource_renders_the_styled_error_page(web_client):
    response = web_client.get("/nonsense")

    page = response.get_data(as_text=True)
    assert response.status_code == 404
    assert "Main navigation" in page
    assert "That page does not exist." in page


def test_navigation_marks_the_current_section(web_client):
    with patch("web.app.APIClient.request", return_value=[]):
        page = web_client.get("/events").get_data(as_text=True)

    assert '<a href="/events" aria-current="page">Events</a>' in page
    assert '<a href="/users" aria-current="page">' not in page


def test_login_fields_keep_visible_labels(web_client):
    page = web_client.get("/login").get_data(as_text=True)

    assert '<label for="username">Username</label>' in page
    assert '<label for="password">Password</label>' in page


def test_client_and_user_are_one_name(web_client):
    """The navigation says Clients, so the page it opens must not say Users."""
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "admin-token"
        browser_session["role"] = "administrator"

    with patch("web.app.APIClient.request", return_value=[]):
        page = web_client.get("/users").get_data(as_text=True)

    assert "<h1>Clients</h1>" in page
    assert "<h1>Users</h1>" not in page


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


def _signed_in_client(web_client, token: str = "client-token"):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = token
        browser_session["role"] = "client"
        browser_session["username"] = "alex"


ACCOUNT = {
    "id": 4,
    "name": "Alex",
    "email": "alex@example.com",
    "age": 30,
    "username": "alex",
    "role": "client",
}


def test_profile_reads_the_account_from_the_token(web_client):
    _signed_in_client(web_client)

    with patch(
        "web.app.APIClient.request", autospec=True, return_value=ACCOUNT
    ) as api_request:
        page = web_client.get("/profile").get_data(as_text=True)

    api_client, method, path = api_request.call_args.args[:3]
    # No id anywhere: the UI never learns one, it asks for "me".
    assert (method, path) == ("GET", "/api/v1/users/me")
    assert api_client.token == "client-token"
    assert 'value="alex@example.com"' in page
    assert "Change password" in page


def test_profile_requires_a_login(web_client):
    assert web_client.get("/profile").status_code == 302
    assert web_client.post("/profile").status_code == 302
    assert web_client.post("/profile/password").status_code == 302


def test_profile_details_patch_users_me_and_follow_a_rename(web_client):
    _signed_in_client(web_client)

    with patch(
        "web.app.APIClient.request",
        return_value={**ACCOUNT, "username": "alexandra"},
    ) as api_request:
        response = web_client.post(
            "/profile",
            data={
                "name": "Alex",
                "email": "alex@example.com",
                "age": "31",
                "username": "alexandra",
            },
        )

    assert response.status_code == 302
    method, path, payload = api_request.call_args.args
    assert (method, path) == ("PATCH", "/api/v1/users/me")
    assert payload == {
        "name": "Alex",
        "email": "alex@example.com",
        "age": "31",
        "username": "alexandra",
    }
    assert "password" not in payload
    with web_client.session_transaction() as browser_session:
        assert browser_session["username"] == "alexandra"


def test_password_form_sends_only_the_password(web_client):
    _signed_in_client(web_client)

    with patch("web.app.APIClient.request", return_value=ACCOUNT) as api_request:
        response = web_client.post(
            "/profile/password",
            data={"password": "a-new-password", "password_confirmation": "a-new-password"},
        )

    assert response.status_code == 302
    patch_calls = [
        call.args for call in api_request.call_args_list if call.args[0] == "PATCH"
    ]
    assert patch_calls == [("PATCH", "/api/v1/users/me", {"password": "a-new-password"})]


def test_password_mismatch_is_caught_before_the_api(web_client):
    _signed_in_client(web_client)

    with patch("web.app.APIClient.request", return_value=ACCOUNT) as api_request:
        response = web_client.post(
            "/profile/password",
            data={"password": "one-value", "password_confirmation": "another-value"},
        )

    page = response.get_data(as_text=True)
    assert response.status_code == 400
    # Only the read that rebuilds the page; nothing was sent as a new password.
    assert [call.args[0] for call in api_request.call_args_list] == ["GET"]
    assert "The two passwords do not match." in page
    assert 'aria-describedby="password_confirmation-error"' in page
    assert "one-value" not in page


def test_the_bootstrap_administrator_profile_explains_itself(web_client):
    with web_client.session_transaction() as browser_session:
        browser_session["access_token"] = "admin-token"
        browser_session["role"] = "administrator"

    with patch(
        "web.app.APIClient.request",
        side_effect=APIClientError("Account not found.", 404),
    ):
        page = web_client.get("/profile").get_data(as_text=True)

    assert "no stored account" in page
    assert "<form" not in page.split("<main")[1].split("</main")[0]


def test_the_client_directory_is_administrator_only(web_client):
    _signed_in_client(web_client)

    for path in ("/users", "/users/4", "/users/4/edit", "/users/4/delete"):
        response = web_client.get(path)
        assert response.status_code == 403, path
        assert b"requires the administrator role" in response.data

    # Signing up is still open to anyone.
    assert web_client.get("/users/new").status_code == 200


def test_navigation_offers_the_profile_and_hides_the_directory(web_client):
    _signed_in_client(web_client)
    with patch("web.app.APIClient.request", return_value=[]):
        page = web_client.get("/events").get_data(as_text=True)

    assert ">My profile</a>" in page
    assert ">Clients</a>" not in page
