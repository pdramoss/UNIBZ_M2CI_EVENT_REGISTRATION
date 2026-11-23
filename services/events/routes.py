"""The event catalogue.

Writes need an administrator; reads are open. The available-seat count is a
subquery over ``registrations``, a table this service does not own but can read,
because all three services share one database.
"""

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status

from common.api import reject_empty_or_null_patch, update_record
from common.database import get_db
from common.dependencies import require_administrator
from common.messages import APIMessageError
from common.models.Administrator import Administrator
from services.events.schemas import EventCreate, EventPatch, EventRead

events_router = APIRouter(prefix="/api/v1", tags=["events"])

ROUTERS = (events_router,)

EVENT_COLUMNS = """
    id, name, date, description, capacity, place,
    (
        SELECT COUNT(*) FROM registrations
        WHERE registrations.event_id = events.id
    ) AS registered
"""


def _read_event(row: sqlite3.Row) -> EventRead:
    return EventRead(
        id=row["id"],
        name=row["name"],
        date=date.fromisoformat(row["date"]),
        description=row["description"],
        capacity=row["capacity"],
        place=row["place"],
        available_seats=max(row["capacity"] - row["registered"], 0),
    )


def _get_event(connection: sqlite3.Connection, event_id: int) -> sqlite3.Row:
    row = connection.execute(
        f"SELECT {EVENT_COLUMNS} FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise APIMessageError(status_code=404, key="event_not_found")
    return row


@events_router.post("/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
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


@events_router.get("/events", response_model=list[EventRead])
def list_events(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    connection: sqlite3.Connection = Depends(get_db),
):
    rows = connection.execute(
        f"SELECT {EVENT_COLUMNS} FROM events ORDER BY id LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [_read_event(row) for row in rows]


@events_router.get("/events/{event_id}", response_model=EventRead)
def get_event(event_id: int, connection: sqlite3.Connection = Depends(get_db)):
    return _read_event(_get_event(connection, event_id))


@events_router.patch("/events/{event_id}", response_model=EventRead)
def update_event(
    event_id: int,
    payload: EventPatch,
    connection: sqlite3.Connection = Depends(get_db),
    administrator: Administrator = Depends(require_administrator),
):
    updates = payload.model_dump(exclude_unset=True)
    reject_empty_or_null_patch(updates)
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
    update_record(
        connection,
        "events",
        event_id,
        updates,
        message_key="event_not_found",
    )
    return _read_event(_get_event(connection, event_id))


@events_router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
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
