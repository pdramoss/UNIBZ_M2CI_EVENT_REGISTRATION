import json
import os
import secrets
from collections.abc import Mapping
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cachelib.file import FileSystemCache
from flask import (
    Flask,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_session import Session
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()

RESOURCE_FIELDS = {
    "users": (
        ("name", "Name", "text"),
        ("email", "Email", "email"),
        ("age", "Age", "number"),
        ("username", "Username", "text"),
    ),
    "events": (
        ("name", "Name", "text"),
        ("date", "Date", "date"),
        ("description", "Description", "text"),
        ("capacity", "Capacity", "number"),
        ("place", "Place", "text"),
    ),
    "registrations": (
        ("date", "Date", "date"),
        ("event_id", "Event ID", "number"),
    ),
}


class APIClientError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class APIClient:
    def __init__(
        self, base_url: str, token: str | None = None, accept_language: str = ""
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.accept_language = accept_language

    def request(
        self, method: str, path: str, payload: Mapping[str, object] | None = None
    ) -> object | None:
        headers = {"Accept": "application/json"}
        if self.accept_language:
            headers["Accept-Language"] = self.accept_language
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        api_request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(api_request, timeout=15) as response:
                response_body = response.read()
        except HTTPError as error:
            error_body = error.read()
            try:
                error_data = json.loads(error_body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = error_body.decode(errors="replace")
            else:
                detail = (
                    error_data.get("detail", error_body.decode(errors="replace"))
                    if isinstance(error_data, dict)
                    else error_body.decode(errors="replace")
                )
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail, ensure_ascii=False)
            raise APIClientError(f"HTTP {error.code}: {detail}", error.code) from error
        except URLError as error:
            raise APIClientError(
                f"Could not connect to the API: {error.reason}", 502
            ) from error

        if not response_body:
            return None
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as error:
            raise APIClientError("The API returned an invalid JSON response") from error


def create_app(test_config: Mapping[str, object] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("WEB_SECRET_KEY") or secrets.token_hex(32),
        API_BASE_URL=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"),
        SESSION_TYPE="cachelib",
        SESSION_CACHELIB=FileSystemCache(
            os.environ.get("SESSION_FILE_DIR", "/tmp/flask-sessions"),
            threshold=500,
            mode=0o600,
        ),
        SESSION_PERMANENT=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("WEB_COOKIE_SECURE", "").lower()
        in {"1", "true", "yes"},
    )
    if test_config:
        app.config.update(test_config)
    Session(app)
    csrf.init_app(app)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            result = APIClient(
                current_app.config["API_BASE_URL"],
                accept_language=request.headers.get("Accept-Language", ""),
            ).request(
                "POST",
                "/api/v1/auth/login",
                {"username": username, "password": password},
            )
        except APIClientError as error:
            return render_template(
                "login.html", error=str(error), username=username
            ), error.status_code

        if not isinstance(result, dict) or not isinstance(
            result.get("access_token"), str
        ):
            return render_template(
                "login.html",
                error="The API login response did not contain an access token.",
                username=username,
            ), 502

        current_app.session_interface.regenerate(session)
        session.clear()
        session["access_token"] = result["access_token"]
        session["role"] = result.get("role")
        session["username"] = username
        flash("You are now logged in.", "success")
        return redirect(url_for("index"))

    @app.post("/logout")
    def logout():
        token = session.get("access_token")
        error_message = None
        if token:
            try:
                APIClient(
                    current_app.config["API_BASE_URL"],
                    token=token,
                    accept_language=request.headers.get("Accept-Language", ""),
                ).request("POST", "/api/v1/auth/logout")
            except APIClientError as error:
                error_message = str(error)
        session.clear()
        if error_message:
            flash(
                "Logged out locally, but the API could not revoke the token: "
                f"{error_message}",
                "error",
            )
        else:
            flash("You are now logged out.", "success")
        return redirect(url_for("index"))

    @app.get("/<resource>")
    def list_records(resource: str):
        _validate_resource(resource)
        denied = _require_role_for_resource(resource, "list")
        if denied:
            return denied

        try:
            limit, offset = _pagination_values()
            records = _api_request(
                "GET",
                f"/api/v1/{resource}?{urlencode({'limit': limit, 'offset': offset})}",
                authenticated=(resource == "registrations"),
            )
        except (APIClientError, ValueError) as error:
            status_code = error.status_code if isinstance(error, APIClientError) else 400
            return render_template(
                "error.html", message=str(error), status_code=status_code
            ), status_code

        if not isinstance(records, list):
            return render_template(
                "error.html",
                message="The API returned an unexpected list response.",
                status_code=502,
            ), 502

        return render_template(
            "list.html",
            resource=resource,
            records=records,
            limit=limit,
            offset=offset,
            previous_offset=max(0, offset - limit),
            can_create=_can_write_resource(resource),
            can_modify=_can_write_resource(resource),
        )

    @app.get("/<resource>/new")
    def new_record(resource: str):
        _validate_resource(resource)
        denied = _require_role_for_resource(resource, "create")
        if denied:
            return denied
        return _render_form(resource, editing=False, values={})

    @app.post("/<resource>/new")
    def create_record(resource: str):
        _validate_resource(resource)
        denied = _require_role_for_resource(resource, "create")
        if denied:
            return denied

        payload = _form_payload(resource, editing=False)
        try:
            result = _api_request("POST", f"/api/v1/{resource}", payload)
        except APIClientError as error:
            return _render_form(
                resource,
                editing=False,
                values=request.form,
                error=str(error),
                status_code=error.status_code,
            )
        flash(f"{resource[:-1].capitalize()} created.", "success")
        if isinstance(result, dict) and isinstance(result.get("id"), int):
            return redirect(
                url_for("record_detail", resource=resource, record_id=result["id"])
            )
        return redirect(url_for("list_records", resource=resource))

    @app.get("/<resource>/<int:record_id>")
    def record_detail(resource: str, record_id: int):
        _validate_resource(resource)
        denied = _require_role_for_resource(resource, "get")
        if denied:
            return denied

        try:
            record = _api_request(
                "GET",
                f"/api/v1/{resource}/{record_id}",
                authenticated=(resource == "registrations"),
            )
        except APIClientError as error:
            return render_template(
                "error.html", message=str(error), status_code=error.status_code
            ), error.status_code
        if not isinstance(record, dict):
            return render_template(
                "error.html",
                message="The API returned an unexpected record response.",
                status_code=502,
            ), 502
        return render_template(
            "detail.html",
            resource=resource,
            record=record,
            can_modify=_can_write_resource(resource),
        )

    @app.route("/<resource>/<int:record_id>/edit", methods=["GET", "POST"])
    def edit_record(resource: str, record_id: int):
        _validate_resource(resource)
        denied = _require_role_for_resource(resource, "update")
        if denied:
            return denied

        if request.method == "GET":
            try:
                record = _api_request(
                    "GET",
                    f"/api/v1/{resource}/{record_id}",
                    authenticated=(resource == "registrations"),
                )
            except APIClientError as error:
                return render_template(
                    "error.html", message=str(error), status_code=error.status_code
                ), error.status_code
            if not isinstance(record, dict):
                return render_template(
                    "error.html",
                    message="The API returned an unexpected record response.",
                    status_code=502,
                ), 502
            return _render_form(
                resource, editing=True, values=record, record_id=record_id
            )

        payload = _form_payload(resource, editing=True)
        try:
            _api_request(
                "PATCH", f"/api/v1/{resource}/{record_id}", payload
            )
        except APIClientError as error:
            return _render_form(
                resource,
                editing=True,
                values=request.form,
                record_id=record_id,
                error=str(error),
                status_code=error.status_code,
            )
        flash(f"{resource[:-1].capitalize()} updated.", "success")
        return redirect(
            url_for("record_detail", resource=resource, record_id=record_id)
        )

    @app.post("/<resource>/<int:record_id>/delete")
    def delete_record(resource: str, record_id: int):
        _validate_resource(resource)
        denied = _require_role_for_resource(resource, "delete")
        if denied:
            return denied

        try:
            _api_request(
                "DELETE",
                f"/api/v1/{resource}/{record_id}",
                authenticated=(resource in {"events", "registrations"}),
            )
        except APIClientError as error:
            flash(str(error), "error")
        else:
            flash(f"{resource[:-1].capitalize()} deleted.", "success")
        return redirect(url_for("list_records", resource=resource))

    @app.route("/accounts/new", methods=["GET", "POST"])
    def new_account():
        denied = _require_role("administrator")
        if denied:
            return denied
        if request.method == "GET":
            return render_template("account_form.html", values={})

        role = request.form.get("role", "")
        if role not in {"client", "administrator"}:
            return render_template(
                "account_form.html",
                values=request.form,
                error="Choose a valid account type.",
            ), 400
        payload = _account_payload()
        endpoint = "clients" if role == "client" else "administrators"
        try:
            _api_request("POST", f"/api/v1/{endpoint}", payload)
        except APIClientError as error:
            return render_template(
                "account_form.html",
                values=request.form,
                error=str(error),
            ), error.status_code
        flash(f"{role.capitalize()} account created.", "success")
        return redirect(url_for("index"))

    return app


def _api_request(
    method: str,
    path: str,
    payload: Mapping[str, object] | None = None,
    *,
    authenticated: bool = True,
) -> object | None:
    token = session.get("access_token") if authenticated else None
    client = APIClient(
        current_app.config["API_BASE_URL"],
        token=token,
        accept_language=request.headers.get("Accept-Language", ""),
    )
    try:
        return client.request(method, path, payload)
    except APIClientError as error:
        if authenticated and error.status_code == 401:
            session.clear()
        raise


def _validate_resource(resource: str) -> None:
    if resource not in RESOURCE_FIELDS:
        abort(404)


def _require_role(required_role: str):
    if not session.get("access_token"):
        flash("Log in to use this feature.", "error")
        return redirect(url_for("login"))
    if session.get("role") != required_role:
        return render_template(
            "error.html",
            message=f"This action requires the {required_role} role.",
            status_code=403,
        ), 403
    return None


def _require_role_for_resource(resource: str, operation: str):
    required_role = None
    if resource == "events" and operation in {"create", "update", "delete"}:
        required_role = "administrator"
    elif resource == "registrations":
        required_role = "client"
    if required_role:
        return _require_role(required_role)
    return None


def _can_write_resource(resource: str) -> bool:
    if resource == "users":
        return True
    if resource == "events":
        return session.get("role") == "administrator"
    return resource == "registrations" and session.get("role") == "client"


def _pagination_values() -> tuple[int, int]:
    try:
        limit = int(request.args.get("limit", "100"))
        offset = int(request.args.get("offset", "0"))
    except ValueError as error:
        raise ValueError("Limit and offset must be whole numbers.") from error
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("Limit must be 1-500 and offset cannot be negative.")
    return limit, offset


def _form_payload(resource: str, editing: bool) -> dict[str, object]:
    fields = [name for name, _, _ in RESOURCE_FIELDS[resource]]
    if resource == "users":
        fields.append("password")
    payload: dict[str, object] = {}
    for name in fields:
        value = request.form.get(name, "").strip()
        if editing and name == "password" and not value:
            continue
        payload[name] = value
    return payload


def _account_payload() -> dict[str, object]:
    return {
        name: request.form.get(name, "").strip()
        for name in ("name", "email", "age", "username", "password")
    }


def _render_form(
    resource: str,
    *,
    editing: bool,
    values: Mapping[str, object],
    record_id: int | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    fields = list(RESOURCE_FIELDS[resource])
    if resource == "users":
        fields.append(
            (
                "password",
                "New password" if editing else "Password",
                "password",
            )
        )
    return (
        render_template(
            "form.html",
            resource=resource,
            fields=fields,
            editing=editing,
            record_id=record_id,
            values=values,
            error=error,
        ),
        status_code,
    )


app = create_app()
