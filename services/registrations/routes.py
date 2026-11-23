"""Client registrations for events.

Every operation needs a client, and a registration is owned: ``user_id`` comes
from the token, never from the payload, and every read and write filters on it.

The capacity check reads ``users`` and ``events`` directly, inside
``BEGIN IMMEDIATE`` so two concurrent bookings cannot both pass it. Those are
tables this service does not own; reading them over the shared database is what
keeps it from having to call the other services.
"""

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status

from common.api import reject_empty_or_null_patch, update_record
from common.database import get_db
from common.dependencies import require_client
from common.messages import APIMessageError
from common.models.Client import Client
from services.registrations.schemas import (
    RegistrationCreate,
    RegistrationPatch,
    RegistrationRead,
)

registrations_router = APIRouter(prefix="/api/v1", tags=["registrations"])

ROUTERS = (registrations_router,)


def _read_registration(row: sqlite3.Row) -> RegistrationRead:
    return RegistrationRead(
        id=row["id"],
        date=date.fromisoformat(row["date"]),
        user_id=row["user_id"],
        event_id=row["event_id"],
    )


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


@registrations_router.post(
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


@registrations_router.get("/registrations", response_model=list[RegistrationRead])
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


@registrations_router.get("/registrations/{registration_id}", response_model=RegistrationRead)
def get_registration(
    registration_id: int,
    connection: sqlite3.Connection = Depends(get_db),
    client: Client = Depends(require_client),
):
    return _read_registration(
        _get_client_registration(connection, registration_id, client.id)
    )


@registrations_router.patch("/registrations/{registration_id}", response_model=RegistrationRead)
def update_registration(
    registration_id: int,
    payload: RegistrationPatch,
    connection: sqlite3.Connection = Depends(get_db),
    client: Client = Depends(require_client),
):
    updates = payload.model_dump(exclude_unset=True)
    reject_empty_or_null_patch(updates)
    connection.execute("BEGIN IMMEDIATE")
    try:
        current = _get_client_registration(connection, registration_id, client.id)
        event_id = updates.get("event_id", current["event_id"])
        _validate_registration(connection, client.id, event_id, registration_id)
        if "date" in updates:
            updates["date"] = updates["date"].isoformat()
        update_record(
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


@registrations_router.delete(
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
