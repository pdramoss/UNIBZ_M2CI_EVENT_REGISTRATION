import json
from unittest.mock import patch
from urllib.request import Request

import pytest

from scripts import api_cli


def test_send_request_posts_json():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"id": 9}'

    with patch("scripts.api_cli.urlopen", return_value=FakeResponse()) as urlopen:
        result = api_cli.send_request(
            "http://localhost:8000/",
            "POST",
            "/api/v1/users",
            {"username": "alex"},
        )

    request = urlopen.call_args.args[0]
    assert isinstance(request, Request)
    assert request.full_url == "http://localhost:8000/api/v1/users"
    assert request.method == "POST"
    assert json.loads(request.data) == {"username": "alex"}
    assert result == {"id": 9}


def test_send_request_adds_bearer_auth_header():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"id": 9}'

    with patch("scripts.api_cli.urlopen", return_value=FakeResponse()) as urlopen:
        api_cli.send_request(
            "http://localhost:8000",
            "POST",
            "/api/v1/events",
            {"name": "Meetup"},
            token="opaque-token",
        )

    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer opaque-token"


def test_cli_maps_create_command_to_api_request(capsys):
    with patch(
        "scripts.api_cli.send_request", return_value={"id": 9}
    ) as send_request:
        result = api_cli.main(
            [
                "--base-url",
                "http://localhost:8000",
                "users",
                "create",
                "--data",
                '{"username":"alex"}',
            ]
        )

    assert result == 0
    send_request.assert_called_once_with(
        "http://localhost:8000",
        "POST",
        "/api/v1/users",
        {"username": "alex"},
        token=None,
    )
    assert json.loads(capsys.readouterr().out) == {"id": 9}


def test_event_cli_uses_api_token(capsys, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "admin-token")

    with patch(
        "scripts.api_cli.send_request", return_value={"id": 9}
    ) as send_request:
        result = api_cli.main(
            [
                "--base-url",
                "http://localhost:8000",
                "events",
                "create",
                "--data",
                '{"name":"Meetup"}',
            ]
        )

    assert result == 0
    send_request.assert_called_once_with(
        "http://localhost:8000",
        "POST",
        "/api/v1/events",
        {"name": "Meetup"},
        token="admin-token",
    )
    assert json.loads(capsys.readouterr().out) == {"id": 9}


def test_event_cli_rejects_missing_api_token(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)

    with pytest.raises(SystemExit) as error:
        api_cli.main(
            ["events", "create", "--data", '{"name":"Meetup"}']
        )

    assert error.value.code == 2


@pytest.mark.parametrize("resource", ["clients", "administrators"])
def test_account_cli_uses_api_token(resource, capsys, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "admin-token")
    payload = {
        "name": "New account",
        "password": "account-password",
        "email": f"{resource}@example.com",
        "age": 30,
        "username": resource,
    }

    with patch(
        "scripts.api_cli.send_request", return_value={"id": 9}
    ) as send_request:
        result = api_cli.main(
            [
                "--base-url",
                "http://localhost:8000",
                resource,
                "create",
                "--data",
                json.dumps(payload),
            ]
        )

    assert result == 0
    send_request.assert_called_once_with(
        "http://localhost:8000",
        "POST",
        f"/api/v1/{resource}",
        payload,
        token="admin-token",
    )
    assert json.loads(capsys.readouterr().out) == {"id": 9}


def test_account_cli_rejects_missing_api_token(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)

    with pytest.raises(SystemExit) as error:
        api_cli.main(
            [
                "administrators",
                "create",
                "--data",
                '{"name":"Admin"}',
            ]
        )

    assert error.value.code == 2


def test_registration_cli_uses_api_token(capsys, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "client-token")

    with patch(
        "scripts.api_cli.send_request", return_value={"id": 9}
    ) as send_request:
        result = api_cli.main(
            [
                "--base-url",
                "http://localhost:8000",
                "registrations",
                "create",
                "--data",
                '{"date":"2026-11-11","event_id":1}',
            ]
        )

    assert result == 0
    send_request.assert_called_once_with(
        "http://localhost:8000",
        "POST",
        "/api/v1/registrations",
        {"date": "2026-11-11", "event_id": 1},
        token="client-token",
    )
    assert json.loads(capsys.readouterr().out) == {"id": 9}


def test_registration_cli_rejects_missing_api_token(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)

    with pytest.raises(SystemExit) as error:
        api_cli.main(
            [
                "registrations",
                "list",
            ]
        )

    assert error.value.code == 2


def test_auth_login_prompts_for_password_and_prints_access_token(capsys):
    with (
        patch("scripts.api_cli.getpass.getpass", return_value="secret"),
        patch(
            "scripts.api_cli.send_request",
            return_value={"access_token": "issued-token"},
        ) as send_request,
    ):
        result = api_cli.main(
            ["--base-url", "http://localhost:8000", "auth", "login", "--username", "alex"]
        )

    assert result == 0
    send_request.assert_called_once_with(
        "http://localhost:8000",
        "POST",
        "/api/v1/auth/login",
        {"username": "alex", "password": "secret"},
        token=None,
    )
    assert capsys.readouterr().out == "issued-token\n"


def test_auth_logout_uses_api_token(capsys, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "issued-token")
    with patch("scripts.api_cli.send_request", return_value=None) as send_request:
        result = api_cli.main(
            ["--base-url", "http://localhost:8000", "auth", "logout"]
        )

    assert result == 0
    send_request.assert_called_once_with(
        "http://localhost:8000",
        "POST",
        "/api/v1/auth/logout",
        None,
        token="issued-token",
    )
    assert capsys.readouterr().out == "Logged out\n"
