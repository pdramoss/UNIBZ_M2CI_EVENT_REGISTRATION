from datetime import date

from app.models.Event import Event
from app.models.Client import Client


class Registration:
    id: int
    date: date
    userId: int
    eventId: int

    def __init__(self, id: int, date: date, client: Client, event: Event) -> None:
        self.id = id
        self.date = date
        self.userId = client.get_id()
        self.eventId = event.get_id()

    def get_id(self) -> int:
        return self.id

    def set_id(self, id: int) -> None:
        self.id = id

    def get_date(self) -> date:
        return self.date

    def set_date(self, date: date) -> None:
        self.date = date

    def get_user_id(self) -> int:
        return self.userId

    def set_user_id(self, user_id: int) -> None:
        self.userId = user_id

    def get_event_id(self) -> int:
        return self.eventId

    def set_event_id(self, event_id: int) -> None:
        self.eventId = event_id