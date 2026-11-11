from datetime import date


class Event:
    id: int
    name: str
    date: date
    description: str
    capacity: int
    place: str

    def __init__(
        self,
        id: int,
        name: str,
        date: date,
        description: str,
        capacity: int,
        place: str,
    ) -> None:
        self.id = id
        self.name = name
        self.date = date
        self.description = description
        self.capacity = capacity
        self.place = place

    def get_id(self) -> int:
        return self.id

    def set_id(self, id: int) -> None:
        self.id = id

    def get_name(self) -> str:
        return self.name

    def set_name(self, name: str) -> None:
        self.name = name

    def get_date(self) -> date:
        return self.date

    def set_date(self, date: date) -> None:
        self.date = date

    def get_description(self) -> str:
        return self.description

    def set_description(self, description: str) -> None:
        self.description = description

    def get_capacity(self) -> int:
        return self.capacity

    def set_capacity(self, capacity: int) -> None:
        self.capacity = capacity

    def get_place(self) -> str:
        return self.place

    def set_place(self, place: str) -> None:
        self.place = place