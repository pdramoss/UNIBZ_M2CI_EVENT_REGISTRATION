import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import HTTPException


MessageKey = Literal[
    "account_not_found",
    "administrator_authentication_required",
    "administrator_credentials_invalid",
    "administrator_credentials_not_configured",
    "bearer_token_invalid",
    "bearer_token_required",
    "client_authentication_required",
    "client_credentials_invalid",
    "duplicate_account",
    "event_capacity_below_registrations",
    "event_capacity_full",
    "event_not_found",
    "insufficient_permissions",
    "invalid_registration_reference",
    "login_credentials_invalid",
    "patch_fields_not_null",
    "patch_fields_required",
    "registration_not_found",
    "user_not_found",
]

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = frozenset({"en", "es"})
_LOCALE_DIRECTORY = Path(__file__).parent.parent / "locales"


class APIMessageError(HTTPException):
    def __init__(
        self,
        *,
        status_code: int,
        key: MessageKey,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=key, headers=headers)
        self.message_key = key


@lru_cache(maxsize=len(SUPPORTED_LOCALES))
def _load_catalog(locale: str) -> dict[str, str]:
    with (_LOCALE_DIRECTORY / f"{locale}.json").open(encoding="utf-8") as catalog_file:
        catalog = json.load(catalog_file)
    if not isinstance(catalog, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in catalog.items()
    ):
        raise ValueError(f"Invalid message catalog: {locale}")
    return catalog


def resolve_locale(accept_language: str | None) -> str:
    if not accept_language:
        return DEFAULT_LOCALE

    candidates: list[tuple[float, int, str]] = []
    for order, language_range in enumerate(accept_language.split(",")):
        parts = language_range.strip().split(";")
        language = parts[0].strip().lower()
        quality = 1.0
        for parameter in parts[1:]:
            name, separator, value = parameter.strip().partition("=")
            if name.strip().lower() == "q":
                if not separator:
                    quality = 0.0
                else:
                    try:
                        quality = float(value)
                    except ValueError:
                        quality = 0.0
                break

        if not 0.0 < quality <= 1.0:
            continue
        if language == "*":
            candidates.append((quality, order, DEFAULT_LOCALE))
            continue

        locale = language.split("-", maxsplit=1)[0]
        if locale in SUPPORTED_LOCALES:
            candidates.append((quality, order, locale))

    if not candidates:
        return DEFAULT_LOCALE
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[2]


def translate_message(
    key: MessageKey,
    accept_language: str | None,
) -> str:
    locale = resolve_locale(accept_language)
    message = _load_catalog(locale).get(key)
    if message is None and locale != DEFAULT_LOCALE:
        message = _load_catalog(DEFAULT_LOCALE).get(key)
    if message is None:
        raise KeyError(f"Message key is missing from catalogs: {key}")
    return message
