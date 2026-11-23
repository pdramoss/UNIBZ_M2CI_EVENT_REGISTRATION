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
        ("event_id", "Event", "select"),
        ("date", "Date", "readonly"),
    ),
}


# One name per resource, so a navigation item never disagrees with the heading of
# the page it opens. The URLs stay aligned with the API paths the gateway routes on.
RESOURCE_LABELS = {
    "users": ("Client", "Clients"),
    "events": ("Event", "Events"),
    "registrations": ("Registration", "My registrations"),
}


DETAIL_FIELD_LABELS = {
    "capacity": "Maximum capacity",
    "available_seats": "Available seats",
}


# Shown when the API gives us no message of its own, or only a structural one.
# Anything the API does say is kept verbatim, because it is already localized.
STATUS_MESSAGES = {
    400: "The request could not be processed. Check the values and try again.",
    401: "Your session has expired. Log in again to continue.",
    403: "You do not have permission to do this.",
    404: "That record could not be found. It may already have been deleted.",
    409: "That change conflicts with data that already exists.",
    422: "Some of the details need correcting.",
    429: "Too many requests were made. Wait a moment and try again.",
    500: "The service ran into a problem. Try again in a moment.",
    502: "The service is unavailable right now. Try again in a moment.",
    503: "The service is unavailable right now. Try again in a moment.",
    504: "The service took too long to answer. Try again in a moment.",
}


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _field_errors_from_detail(detail: object) -> dict[str, str]:
    """Turn a FastAPI 422 detail list into {field name: readable message}.

    The API answers an invalid payload with a list of
    ``{"loc": ["body", "email"], "msg": ..., "type": ...}`` entries. Rendering
    that list as JSON tells the user nothing, so each entry is attached to the
    field it belongs to instead.
    """
    if not isinstance(detail, list):
        return {}
    field_errors: dict[str, str] = {}
    for item in detail:
        if not isinstance(item, dict) or not isinstance(item.get("msg"), str):
            continue
        location = item.get("loc")
        if not isinstance(location, (list, tuple)) or not location:
            continue
        field_errors.setdefault(str(location[-1]), _sentence(item["msg"]))
    return field_errors


class APIClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int = 502,
        *,
        field_errors: Mapping[str, str] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.field_errors: dict[str, str] = dict(field_errors or {})


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
                detail: object = error_body.decode(errors="replace")
            else:
                detail = (
                    error_data.get("detail")
                    if isinstance(error_data, dict)
                    else error_data
                )
            field_errors = _field_errors_from_detail(detail)
            if isinstance(detail, str) and detail.strip():
                # The API already localized this message for the request's
                # Accept-Language, so it is shown exactly as it arrived.
                message = _sentence(detail)
            else:
                message = STATUS_MESSAGES.get(error.code, STATUS_MESSAGES[502])
            raise APIClientError(
                message, error.code, field_errors=field_errors
            ) from error
        except URLError:
            raise APIClientError(STATUS_MESSAGES[502], 502) from None

        if not response_body:
            return None
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as error:
            raise APIClientError(STATUS_MESSAGES[502], 502) from error


def create_app(test_config: Mapping[str, object] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("WEB_SECRET_KEY") or secrets.token_hex(32),
        GATEWAY_URL=os.environ.get("GATEWAY_URL", "http://127.0.0.1:9000"),
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

    @app.context_processor
    def inject_template_defaults():
        return {"resource_label": _resource_label, "field_errors": {}}

    @app.errorhandler(404)
    def page_not_found(_error):
        return render_template(
            "error.html",
            message=(
                "That page does not exist. Use the navigation at the top to reach "
                "events, clients or your registrations."
            ),
            status_code=404,
        ), 404

    @app.errorhandler(500)
    def internal_error(_error):
        return render_template(
            "error.html",
            message=(
                "The page could not be built because of an unexpected problem. "
                "Try again in a moment."
            ),
            status_code=500,
        ), 500

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
                current_app.config["GATEWAY_URL"],
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
                    current_app.config["GATEWAY_URL"],
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
                authenticated=(resource != "events"),
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
                field_errors=error.field_errors,
                status_code=error.status_code,
            )
        flash(f"{_resource_label(resource)} created.", "success")
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
                authenticated=(resource != "events"),
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
            field_labels=DETAIL_FIELD_LABELS,
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
                    authenticated=(resource != "events"),
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
                field_errors=error.field_errors,
                status_code=error.status_code,
            )
        flash(f"{_resource_label(resource)} updated.", "success")
        return redirect(
            url_for("record_detail", resource=resource, record_id=record_id)
        )

    @app.route("/<resource>/<int:record_id>/delete", methods=["GET", "POST"])
    def delete_record(resource: str, record_id: int):
        _validate_resource(resource)
        denied = _require_role_for_resource(resource, "delete")
        if denied:
            return denied

        if request.method == "GET":
            # Deleting cannot be undone, so GET names the record and asks first;
            # the POST below is what actually deletes it.
            try:
                record = _api_request(
                    "GET",
                    f"/api/v1/{resource}/{record_id}",
                    authenticated=(resource != "events"),
                )
            except APIClientError as error:
                return render_template(
                    "error.html", message=str(error), status_code=error.status_code
                ), error.status_code
            if not isinstance(record, dict):
                return render_template(
                    "error.html",
                    message="That record could not be read, so nothing was deleted.",
                    status_code=502,
                ), 502
            return render_template(
                "confirm_delete.html",
                resource=resource,
                record=record,
                record_id=record_id,
            )

        try:
            _api_request(
                "DELETE",
                f"/api/v1/{resource}/{record_id}",
                authenticated=True,
            )
        except APIClientError as error:
            flash(str(error), "error")
        else:
            flash(f"{_resource_label(resource)} deleted.", "success")
        return redirect(url_for("list_records", resource=resource))

    @app.get("/profile")
    def profile():
        denied = _require_login()
        if denied:
            return denied
        account = _own_account()
        if isinstance(account, str):
            return render_template("profile.html", account=None, missing=account)
        return render_template("profile.html", account=account, missing=None)

    @app.post("/profile")
    def update_profile():
        denied = _require_login()
        if denied:
            return denied

        payload = {
            name: request.form.get(name, "").strip()
            for name in ("name", "email", "age", "username")
        }
        try:
            updated = _api_request("PATCH", "/api/v1/users/me", payload)
        except APIClientError as error:
            return render_template(
                "profile.html",
                account=request.form,
                missing=None,
                error=str(error),
                field_errors=error.field_errors,
            ), error.status_code
        if isinstance(updated, dict) and isinstance(updated.get("username"), str):
            # The header shows the username, so it has to follow a rename.
            session["username"] = updated["username"]
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    @app.post("/profile/password")
    def change_password():
        denied = _require_login()
        if denied:
            return denied

        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        account = _own_account()
        if password != confirmation:
            # Caught here so a typo never reaches the API as a new password.
            return render_template(
                "profile.html",
                account=None if isinstance(account, str) else account,
                missing=account if isinstance(account, str) else None,
                password_field_errors={
                    "password_confirmation": "The two passwords do not match."
                },
            ), 400
        try:
            _api_request("PATCH", "/api/v1/users/me", {"password": password})
        except APIClientError as error:
            return render_template(
                "profile.html",
                account=None if isinstance(account, str) else account,
                missing=account if isinstance(account, str) else None,
                password_error=str(error),
                password_field_errors=error.field_errors,
            ), error.status_code
        flash("Password changed.", "success")
        return redirect(url_for("profile"))

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
                field_errors={"role": "Choose a valid account type."},
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
                field_errors=error.field_errors,
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
        current_app.config["GATEWAY_URL"],
        token=token,
        accept_language=request.headers.get("Accept-Language", ""),
    )
    try:
        return client.request(method, path, payload)
    except APIClientError as error:
        if authenticated and error.status_code == 401:
            session.clear()
        raise


def _resource_label(resource: str, plural: bool = False) -> str:
    names = RESOURCE_LABELS.get(
        resource, (resource[:-1].capitalize(), resource.capitalize())
    )
    return names[1] if plural else names[0]


def _validate_resource(resource: str) -> None:
    if resource not in RESOURCE_FIELDS:
        abort(404)


def _require_login():
    if not session.get("access_token"):
        flash("Log in to use this feature.", "error")
        return redirect(url_for("login"))
    return None


def _own_account() -> dict | str:
    """The signed-in account, or a sentence explaining why there is none.

    The bootstrap administrator authenticates from environment variables and has
    no stored record, so the API answers 404 and there is nothing to edit.
    """
    try:
        account = _api_request("GET", "/api/v1/users/me")
    except APIClientError as error:
        if error.status_code == 404:
            return (
                "This administrator signs in with the credentials configured for "
                "the deployment and has no stored account to edit."
            )
        return str(error)
    if not isinstance(account, dict):
        return "Your account could not be read."
    return account


def _require_role(required_role: str):
    denied = _require_login()
    if denied:
        return denied
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
    elif resource == "users" and operation != "create":
        # A client manages its own account at /profile; the directory of client
        # records is personal data and belongs to administrators. "create" stays
        # open because it is the signup form.
        required_role = "administrator"
    if required_role:
        return _require_role(required_role)
    return None


def _can_write_resource(resource: str) -> bool:
    if resource in {"users", "events"}:
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
    if resource == "registrations" and payload.get("event_id"):
        event_date = _event_date(payload["event_id"])
        if event_date:
            payload["date"] = event_date
    return payload


def _account_payload() -> dict[str, object]:
    return {
        name: request.form.get(name, "").strip()
        for name in ("name", "email", "age", "username", "password")
    }


def _event_options() -> list[tuple[str, str, str]]:
    try:
        events = _api_request(
            "GET",
            f"/api/v1/events?{urlencode({'limit': 500, 'offset': 0})}",
            authenticated=False,
        )
    except APIClientError:
        return []
    if not isinstance(events, list):
        return []
    return [
        (
            str(event["id"]),
            f"{event.get('name', '')} — {event.get('date', '')} (#{event['id']})",
            str(event.get("date", "")),
        )
        for event in events
        if isinstance(event, dict) and isinstance(event.get("id"), int)
    ]


def _event_date(event_id: object) -> str | None:
    try:
        event = _api_request(
            "GET", f"/api/v1/events/{int(str(event_id))}", authenticated=False
        )
    except (APIClientError, ValueError):
        return None
    if isinstance(event, dict) and isinstance(event.get("date"), str):
        return event["date"]
    return None


def _render_form(
    resource: str,
    *,
    editing: bool,
    values: Mapping[str, object],
    record_id: int | None = None,
    error: str | None = None,
    field_errors: Mapping[str, str] | None = None,
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
    options: dict[str, list[tuple[str, str]]] = {}
    if resource == "registrations":
        options["event_id"] = _event_options()
    return (
        render_template(
            "form.html",
            resource=resource,
            fields=fields,
            editing=editing,
            record_id=record_id,
            values=values,
            options=options,
            error=error,
            field_errors=field_errors or {},
        ),
        status_code,
    )


app = create_app()
