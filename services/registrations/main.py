"""The registrations service: the ASGI app its container runs."""

from common.service import build_service
from services.registrations.routes import ROUTERS

app = build_service(
    name="registrations",
    description=(
        "Client registrations for events, including the capacity check that "
        "admits or rejects one."
    ),
    routers=ROUTERS,
)
