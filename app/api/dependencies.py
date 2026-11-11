import sqlite3
from datetime import datetime, timezone

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_db
from app.core.messages import APIMessageError
from app.core.security import hash_session_token
from app.models.Administrator import Administrator
from app.models.Client import Client

_bearer_auth = HTTPBearer(auto_error=False)


def require_authenticated_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_auth),
    connection: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row:
    if credentials is None:
        raise APIMessageError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            key="bearer_token_required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(timezone.utc).isoformat()
    session = connection.execute(
        """
        SELECT
            sessions.token_hash,
            sessions.user_id,
            sessions.role,
            sessions.username,
            users.name,
            users.email,
            users.age,
            users.username AS account_username,
            users.role AS account_role
        FROM auth_sessions AS sessions
        LEFT JOIN users ON users.id = sessions.user_id
        WHERE sessions.token_hash = ? AND sessions.expires_at > ?
        """,
        (hash_session_token(credentials.credentials), now),
    ).fetchone()
    if session is None or (
        session["user_id"] is not None
        and session["account_role"] != session["role"]
    ):
        raise APIMessageError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            key="bearer_token_invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return session


def require_administrator(
    session: sqlite3.Row = Depends(require_authenticated_session),
) -> Administrator:
    if session["role"] != "administrator":
        raise APIMessageError(
            status_code=status.HTTP_403_FORBIDDEN,
            key="insufficient_permissions",
        )

    if session["user_id"] is None:
        return Administrator(
            id=0,
            name=session["username"],
            password="",
            email="",
            age=0,
            username=session["username"],
        )

    return Administrator(
        id=session["user_id"],
        name=session["name"],
        password="",
        email=session["email"],
        age=session["age"],
        username=session["account_username"],
    )


def require_client(
    session: sqlite3.Row = Depends(require_authenticated_session),
) -> Client:
    if session["role"] != "client":
        raise APIMessageError(
            status_code=status.HTTP_403_FORBIDDEN,
            key="insufficient_permissions",
        )

    return Client(
        id=session["user_id"],
        name=session["name"],
        password="",
        email=session["email"],
        age=session["age"],
        username=session["account_username"],
    )
