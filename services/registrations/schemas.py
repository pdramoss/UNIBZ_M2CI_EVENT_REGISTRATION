"""The registrations service's request and response models."""

from datetime import date as Date

from pydantic import Field

from common.schemas import APIModel


class RegistrationCreate(APIModel):
    date: Date
    event_id: int = Field(gt=0)


class RegistrationPatch(APIModel):
    date: Date | None = None
    event_id: int | None = Field(default=None, gt=0)


class RegistrationRead(APIModel):
    id: int
    date: Date
    user_id: int
    event_id: int
