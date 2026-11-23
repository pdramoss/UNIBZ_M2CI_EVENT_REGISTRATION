"""The accounts service's request and response models."""

from typing import Literal

from pydantic import Field

from common.schemas import APIModel


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
