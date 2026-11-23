"""Authentication and account records.

This service owns ``/api/v1/auth`` and the user, client and administrator
records. It is the only service that issues a session, but not the only one that
reads it: the other two resolve a token by querying ``auth_sessions`` themselves,
which is why none of them has to call this one.
"""

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status

from common.api import reject_empty_or_null_patch, update_record
from common.database import get_db
from common.dependencies import require_administrator, require_authenticated_session
from common.messages import APIMessageError
from common.models.Administrator import Administrator
from common.security import (
    SESSION_LIFETIME_SECONDS,
    create_session_token,
    hash_password,
    hash_session_token,
    session_expiration,
    verify_password,
)
from services.accounts.schemas import (
    AdministratorCreate,
    ClientCreate,
    LoginRequest,
    LoginResponse,
    UserCreate,
    UserPatch,
    UserRead,
)

# Two routers, one service: the gateway routes /api/v1/auth and the account
# resources here, and this app includes both.
auth_router = APIRouter(prefix="/api/v1", tags=["auth"])
accounts_router = APIRouter(prefix="/api/v1", tags=["accounts"])

ROUTERS = (auth_router, accounts_router)

AccountRole = Literal["client", "administrator"]


@auth_router.post("/auth/login", response_model=LoginResponse)
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


@auth_router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
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


@accounts_router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, connection: sqlite3.Connection = Depends(get_db)):
    return _create_account(payload, "client", connection)


@accounts_router.post("/clients", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    connection: sqlite3.Connection = Depends(get_db),
    administrator: Administrator = Depends(require_administrator),
):
    return _create_account(payload, "client", connection)


@accounts_router.post(
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


def _session_user_id(session: sqlite3.Row) -> int:
    """The id of the account behind a session.

    The bootstrap administrator authenticates from environment variables and has
    no ``users`` row, so its session carries ``user_id IS NULL``. There is no
    record to read or change, which is a 404 rather than an error.
    """
    if session["user_id"] is None:
        raise APIMessageError(status_code=404, key="account_not_found")
    return session["user_id"]


def _require_account_access(session: sqlite3.Row, user_id: int) -> None:
    """A user record belongs to its owner; administrators may reach any of them."""
    if session["role"] == "administrator":
        return
    if session["user_id"] != user_id:
        raise APIMessageError(status_code=403, key="insufficient_permissions")


def _update_user(
    connection: sqlite3.Connection, user_id: int, payload: UserPatch
) -> UserRead:
    _get_user(connection, user_id)
    updates = payload.model_dump(exclude_unset=True)
    reject_empty_or_null_patch(updates)
    if "password" in updates:
        updates["password_hash"] = hash_password(updates.pop("password"))
    try:
        update_record(
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


@accounts_router.get("/users", response_model=list[UserRead])
def list_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection = Depends(get_db),
    administrator: Administrator = Depends(require_administrator),
):
    rows = connection.execute(
        """
        SELECT id, name, email, age, username, role
        FROM users WHERE role = 'client' ORDER BY id LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [_read_user(row) for row in rows]


# Declared before /users/{user_id}: FastAPI matches in declaration order, so the
# parameterised route would otherwise claim "me" and fail to parse it as an int.
@accounts_router.get("/users/me", response_model=UserRead)
def read_own_account(
    connection: sqlite3.Connection = Depends(get_db),
    session: sqlite3.Row = Depends(require_authenticated_session),
):
    """The account behind the bearer token, so a client needs no id of its own."""
    return _read_user(_get_user(connection, _session_user_id(session)))


@accounts_router.patch("/users/me", response_model=UserRead)
def update_own_account(
    payload: UserPatch,
    connection: sqlite3.Connection = Depends(get_db),
    session: sqlite3.Row = Depends(require_authenticated_session),
):
    return _update_user(connection, _session_user_id(session), payload)


@accounts_router.get("/users/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    connection: sqlite3.Connection = Depends(get_db),
    session: sqlite3.Row = Depends(require_authenticated_session),
):
    _require_account_access(session, user_id)
    return _read_user(_get_user(connection, user_id))


@accounts_router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserPatch,
    connection: sqlite3.Connection = Depends(get_db),
    session: sqlite3.Row = Depends(require_authenticated_session),
):
    _require_account_access(session, user_id)
    return _update_user(connection, user_id, payload)


@accounts_router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    connection: sqlite3.Connection = Depends(get_db),
    session: sqlite3.Row = Depends(require_authenticated_session),
):
    _require_account_access(session, user_id)
    cursor = connection.execute(
        "DELETE FROM users WHERE id = ? AND role = 'client'", (user_id,)
    )
    if cursor.rowcount == 0:
        raise APIMessageError(status_code=404, key="user_not_found")
    connection.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
