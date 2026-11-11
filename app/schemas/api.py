from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1)
    email: str = Field(min_length=3, max_length=254)
    age: int = Field(ge=0)
    username: str = Field(min_length=1, max_length=50)


class ClientCreate(UserCreate):
    pass


class AdministratorCreate(UserCreate):
    pass


class LoginRequest(APIModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1)


class LoginResponse(APIModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    role: Literal["client", "administrator"]


class UserPatch(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=1)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    age: int | None = Field(default=None, ge=0)
    username: str | None = Field(default=None, min_length=1, max_length=50)


class UserRead(APIModel):
    id: int
    name: str
    email: str
    age: int
    username: str
    role: Literal["client", "administrator"]


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
