"""Route helpers shared by more than one service.

Everything else in a service's ``routes.py`` is private to that service. These
two are not: they encode how the whole API updates a row and how it rejects an
empty PATCH, and all three services have to answer identically.
"""

import sqlite3

from common.messages import APIMessageError, MessageKey


def update_record(
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


def reject_empty_or_null_patch(updates: dict[str, object]) -> None:
    if not updates:
        raise APIMessageError(status_code=422, key="patch_fields_required")
    if any(value is None for value in updates.values()):
        raise APIMessageError(status_code=422, key="patch_fields_not_null")
