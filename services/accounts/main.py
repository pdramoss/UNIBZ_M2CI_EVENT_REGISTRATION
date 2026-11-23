"""The accounts service: the ASGI app its container runs."""

from common.service import build_service
from services.accounts.routes import ROUTERS

app = build_service(
    name="accounts",
    description=(
        "Authentication and accounts: login, logout, and the user, client and "
        "administrator records."
    ),
    routers=ROUTERS,
)
