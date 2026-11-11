import base64
import binascii
import hashlib
import secrets
from datetime import datetime, timedelta, timezone


_HASH_ALGORITHM = "sha256"
_HASH_ITERATIONS = 600_000
SESSION_LIFETIME = timedelta(hours=24)
SESSION_LIFETIME_SECONDS = int(SESSION_LIFETIME.total_seconds())


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        _HASH_ALGORITHM,
        password.encode("utf-8"),
        salt,
        _HASH_ITERATIONS,
    )
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii")
    encoded_hash = base64.urlsafe_b64encode(password_hash).decode("ascii")
    return f"pbkdf2_{_HASH_ALGORITHM}${_HASH_ITERATIONS}${encoded_salt}${encoded_hash}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_expected_hash = (
            encoded_hash.split("$")
        )
        if (
            algorithm != f"pbkdf2_{_HASH_ALGORITHM}"
            or int(iterations) != _HASH_ITERATIONS
        ):
            return False

        salt = base64.b64decode(encoded_salt, altchars=b"-_", validate=True)
        expected_hash = base64.b64decode(
            encoded_expected_hash, altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error):
        return False

    if len(salt) != 16 or len(expected_hash) != hashlib.sha256().digest_size:
        return False

    actual_hash = hashlib.pbkdf2_hmac(
        _HASH_ALGORITHM,
        password.encode("utf-8"),
        salt,
        _HASH_ITERATIONS,
    )
    return secrets.compare_digest(actual_hash, expected_hash)


def create_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiration(now: datetime | None = None) -> datetime:
    current_time = now or datetime.now(timezone.utc)
    return current_time + SESSION_LIFETIME
