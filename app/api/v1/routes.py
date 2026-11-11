import os
import secrets
import sqlite3
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import (
    require_administrator,
    require_authenticated_session,
    require_client,
)
from app.core.database import get_db
from app.core.messages import APIMessageError, MessageKey
from app.core.security import (
    SESSION_LIFETIME_SECONDS,
    create_session_token,
    hash_password,
    hash_session_token,
    session_expiration,
    verify_password,
)
from app.models.Administrator import Administrator
from app.models.Client import Client
from app.schemas.api import (
    AdministratorCreate,
    ClientCreate,
    EventCreate,
    EventPatch,
    EventRead,
    LoginRequest,
    LoginResponse,
    RegistrationCreate,
    RegistrationPatch,
    RegistrationRead,
    UserCreate,
    UserPatch,
    UserRead,
)

router = APIRouter(prefix="/api/v1")

AccountRole = Literal["client", "administrator"]


@router.post("/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    connection: sqlite3.Connection = Depends(get_db),
):
    configured_username = os.environ.get("ADMIN_USERNAME")
    configured_password = os.environ.get("ADMIN_PASSWORD")

    if (
        configured_username
        and configured_password
        and secrets.compare_digest(
            payload.username.encode("utf-8"), configured_username.encode("utf-8")
        )
        and secrets.compare_digest(
            payload.password.encode("utf-8"), configured_password.encode("utf-8")
        )
    ):
        user_id = None
        role: AccountRole = "administrator"
        username = payload.username
    else:
        user = connection.execute(
            """
            SELECT id, password_hash, username, role
            FROM users WHERE username = ?
            """,
            (payload.username,),
        ).fetchone()
        if user is None or not verify_password(
            payload.password, user["password_hash"]
        ):
            raise APIMessageError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                key="login_credentials_invalid",
            )
        user_id = user["id"]
        role = user["role"]
        username = user["username"]

    now = datetime.now(timezone.utc)
    expires_at = session_expiration(now)
    token = create_session_token()
    connection.execute(
        "DELETE FROM auth_sessions WHERE expires_at <= ?", (now.isoformat(),)
    )
    connection.execute(
        """
        INSERT INTO auth_sessions (token_hash, user_id, role, username, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            hash_session_token(token),
            user_id,
            role,
            username,
            expires_at.isoformat(),
        ),
    )
    connection.commit()
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=SESSION_LIFETIME_SECONDS,
        role=role,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    session: sqlite3.Row = Depends(require_authenticated_session),
    connection: sqlite3.Connection = Depends(get_db),
):
    connection.execute(
        "DELETE FROM auth_sessions WHERE token_hash = ?", (session["token_hash"],)
    )
    connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _read_user(row: sqlite3.Row) -> UserRead:
    return UserRead(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        age=row["age"],
        username=row["username"],
        role=row["role"],
    )


def _read_event(row: sqlite3.Row) -> EventRead:
    return EventRead(
        id=row["id"],
        name=row["name"],
        date=date.fromisoformat(row["date"]),
        description=row["description"],
        capacity=row["capacity"],
        place=row["place"],
    )


def _read_registration(row: sqlite3.Row) -> RegistrationRead:
    return RegistrationRead(
        id=row["id"],
        date=date.fromisoformat(row["date"]),
        user_id=row["user_id"],
        event_id=row["event_id"],
    )


def _get_user(connection: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, name, email, age, username, role
        FROM users WHERE id = ? AND role = 'client'
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        raise APIMessageError(status_code=404, key="user_not_found")
    return row


def _get_account(connection: sqlite3.Connection, account_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, name, email, age, username, role
        FROM users WHERE id = ?
        """,
        (account_id,),
    ).fetchone()
    if row is None:
        raise APIMessageError(status_code=404, key="account_not_found")
    return row


def _create_account(
    payload: UserCreate,
    role: AccountRole,
    connection: sqlite3.Connection,
) -> UserRead:
    try:
        cursor = connection.execute(
            """
            INSERT INTO users (name, password_hash, email, age, username, role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                hash_password(payload.password),
                payload.email,
                payload.age,
                payload.username,
                role,
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise APIMessageError(
            status_code=409, key="duplicate_account"
        ) from error
    return _read_user(_get_account(connection, cursor.lastrowid))


def _get_event(connection: sqlite3.Connection, event_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT id, name, date, description, capacity, place FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise APIMessageError(status_code=404, key="event_not_found")
    return row


def _get_registration(
    connection: sqlite3.Connection, registration_id: int
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT id, date, user_id, event_id FROM registrations WHERE id = ?",
        (registration_id,),
    ).fetchone()
    if row is None:
        raise APIMessageError(status_code=404, key="registration_not_found")
    return row


def _get_client_registration(
    connection: sqlite3.Connection, registration_id: int, client_id: int
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, date, user_id, event_id
        FROM registrations WHERE id = ? AND user_id = ?
        """,
        (registration_id, client_id),
    ).fetchone()
    if row is None:
        raise APIMessageError(status_code=404, key="registration_not_found")
    return row


def _update_record(
    connection: sqlite3.Connection,
    table: str,
    record_id: int,
    updates: dict[str, object],
    message_key: MessageKey,
) -> None:
    assignments = ", ".join(f"{column} = ?" for column in updates)
    cursor = connection.execute(
        f"UPDATE {table} SET {assignments} WHERE id = ?",
        (*updates.values(), record_id),
    )
    if cursor.rowcount == 0:
        raise APIMessageError(status_code=404, key=message_key)
    connection.commit()


def _validate_registration(
    connection: sqlite3.Connection,
    user_id: int,
    event_id: int,
    registration_id: int | None = None,
) -> None:
    if (
        connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        is None
    ):
        raise APIMessageError(status_code=404, key="user_not_found")

    event = connection.execute(
        "SELECT capacity FROM events WHERE id = ?", (event_id,)
    ).fetchone()
    if event is None:
        raise APIMessageError(status_code=404, key="event_not_found")

    if registration_id is None:
        count_query = "SELECT COUNT(*) FROM registrations WHERE event_id = ?"
        count_parameters = (event_id,)
    else:
        count_query = (
            "SELECT COUNT(*) FROM registrations WHERE event_id = ? AND id != ?"
        )
        count_parameters = (event_id, registration_id)

    registration_count = connection.execute(
        count_query, count_parameters
    ).fetchone()[0]
    if registration_count >= event["capacity"]:
        raise APIMessageError(status_code=409, key="event_capacity_full")


def _reject_empty_or_null_patch(updates: dict[str, object]) -> None:
    if not updates:
        raise APIMessageError(status_code=422, key="patch_fields_required")
    if any(value is None for value in updates.values()):
        raise APIMessageError(status_code=422, key="patch_fields_not_null")


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, connection: sqlite3.Connection = Depends(get_db)):
    return _create_account(payload, "client", connection)


@router.post("/clients", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    connection: sqlite3.Connection = Depends(get_db),
    administrator: Administrator = Depends(require_administrator),
):
    return _create_account(payload, "client", connection)


@router.post(
    "/administrators",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_administrator(
    payload: AdministratorCreate,
    connection: sqlite3.Connection = Depends(get_db),
    administrator: Administrator = Depends(require_administrator),
):
    return _create_account(payload, "administrator", connection)


@router.get("/users", response_model=list[UserRead])
def list_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection = Depends(get_db),
):
    rows = connection.execute(
        """
        SELECT id, name, email, age, username, role
        FROM users WHERE role = 'client' ORDER BY id LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [_read_user(row) for row in rows]


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(user_id: int, connection: sqlite3.Connection = Depends(get_db)):
    return _read_user(_get_user(connection, user_id))


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserPatch,
    connection: sqlite3.Connection = Depends(get_db),
):
    _get_user(connection, user_id)
    updates = payload.model_dump(exclude_unset=True)
    _reject_empty_or_null_patch(updates)
    if "password" in updates:
        updates["password_hash"] = hash_password(updates.pop("password"))
    try:
        _update_record(
            connection,
            "users",
            user_id,
            updates,
            message_key="user_not_found",
        )
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise APIMessageError(
            status_code=409, key="duplicate_account"
        ) from error
    return _read_user(_get_user(connection, user_id))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, connection: sqlite3.Connection = Depends(get_db)):
    cursor = connection.execute(
        "DELETE FROM users WHERE id = ? AND role = 'client'", (user_id,)
    )
    if cursor.rowcount == 0:
        raise APIMessageError(status_code=404, key="user_not_found")
    connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    connection: sqlite3.Connection = Depends(get_db),
    administrator: Administrator = Depends(require_administrator),
):
    cursor = connection.execute(
        """
        INSERT INTO events (name, date, description, capacity, place)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            payload.name,
            payload.date.isoformat(),
            payload.description,
            payload.capacity,
            payload.place,
        ),
    )
    connection.commit()
    return _read_event(_get_event(connection, cursor.lastrowid))


@router.get("/events", response_model=list[EventRead])
def list_events(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection = Depends(get_db),
):
    rows = connection.execute(
        """
        SELECT id, name, date, description, capacity, place
        FROM events ORDER BY id LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [_read_event(row) for row in rows]


@router.get("/events/{event_id}", response_model=EventRead)
def get_event(event_id: int, connection: sqlite3.Connection = Depends(get_db)):
    return _read_event(_get_event(connection, event_id))


@router.patch("/events/{event_id}", response_model=EventRead)
def update_event(
    event_id: int,
    payload: EventPatch,
    connection: sqlite3.Connection = Depends(get_db),
    administrator: Administrator = Depends(require_administrator),
):
    updates = payload.model_dump(exclude_unset=True)
    _reject_empty_or_null_patch(updates)
    _get_event(connection, event_id)
    if "date" in updates:
        updates["date"] = updates["date"].isoformat()
    if "capacity" in updates:
        registrations = connection.execute(
            "SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,)
        ).fetchone()[0]
        if updates["capacity"] < registrations:
            raise APIMessageError(
                status_code=409,
                key="event_capacity_below_registrations",
            )
    _update_record(
        connection,
        "events",
        event_id,
        updates,
        message_key="event_not_found",
    )
    return _read_event(_get_event(connection, event_id))


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    connection: sqlite3.Connection = Depends(get_db),
    administrator: Administrator = Depends(require_administrator),
):
    cursor = connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
    if cursor.rowcount == 0:
        raise APIMessageError(status_code=404, key="event_not_found")
    connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/registrations",
    response_model=RegistrationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_registration(
    payload: RegistrationCreate,
    connection: sqlite3.Connection = Depends(get_db),
    client: Client = Depends(require_client),
):
    connection.execute("BEGIN IMMEDIATE")
    try:
        _validate_registration(connection, client.id, payload.event_id)
        cursor = connection.execute(
            """
            INSERT INTO registrations (date, user_id, event_id)
            VALUES (?, ?, ?)
            """,
            (payload.date.isoformat(), client.id, payload.event_id),
        )
        connection.commit()
    except APIMessageError:
        connection.rollback()
        raise
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise APIMessageError(
            status_code=409, key="invalid_registration_reference"
        ) from error
    return _read_registration(_get_registration(connection, cursor.lastrowid))


@router.get("/registrations", response_model=list[RegistrationRead])
def list_registrations(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection = Depends(get_db),
    client: Client = Depends(require_client),
):
    rows = connection.execute(
        """
        SELECT id, date, user_id, event_id
        FROM registrations WHERE user_id = ? ORDER BY id LIMIT ? OFFSET ?
        """,
        (client.id, limit, offset),
    ).fetchall()
    return [_read_registration(row) for row in rows]


@router.get("/registrations/{registration_id}", response_model=RegistrationRead)
def get_registration(
    registration_id: int,
    connection: sqlite3.Connection = Depends(get_db),
    client: Client = Depends(require_client),
):
    return _read_registration(
        _get_client_registration(connection, registration_id, client.id)
    )


@router.patch("/registrations/{registration_id}", response_model=RegistrationRead)
def update_registration(
    registration_id: int,
    payload: RegistrationPatch,
    connection: sqlite3.Connection = Depends(get_db),
    client: Client = Depends(require_client),
):
    updates = payload.model_dump(exclude_unset=True)
    _reject_empty_or_null_patch(updates)
    connection.execute("BEGIN IMMEDIATE")
    try:
        current = _get_client_registration(connection, registration_id, client.id)
        event_id = updates.get("event_id", current["event_id"])
        _validate_registration(connection, client.id, event_id, registration_id)
        if "date" in updates:
            updates["date"] = updates["date"].isoformat()
        _update_record(
            connection,
            "registrations",
            registration_id,
            updates,
            message_key="registration_not_found",
        )
    except APIMessageError:
        connection.rollback()
        raise
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise APIMessageError(
            status_code=409, key="invalid_registration_reference"
        ) from error
    return _read_registration(_get_registration(connection, registration_id))


@router.delete(
    "/registrations/{registration_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_registration(
    registration_id: int,
    connection: sqlite3.Connection = Depends(get_db),
    client: Client = Depends(require_client),
):
    cursor = connection.execute(
        "DELETE FROM registrations WHERE id = ? AND user_id = ?",
        (registration_id, client.id),
    )
    if cursor.rowcount == 0:
        raise APIMessageError(status_code=404, key="registration_not_found")
    connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
