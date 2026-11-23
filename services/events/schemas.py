"""The events service's request and response models."""

from datetime import date as Date

from pydantic import Field

from common.schemas import APIModel


class EventCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    date: Date
    description: str
    capacity: int = Field(ge=0)
    place: str = Field(min_length=1, max_length=200)


class EventPatch(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    date: Date | None = None
    description: str | None = None
    capacity: int | None = Field(default=None, ge=0)
    place: str | None = Field(default=None, min_length=1, max_length=200)


class EventRead(APIModel):
    id: int
    name: str
    date: Date
    description: str
    capacity: int
    place: str
    available_seats: int
