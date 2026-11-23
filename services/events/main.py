"""The events service: the ASGI app its container runs."""

from common.service import build_service
from services.events.routes import ROUTERS

app = build_service(
    name="events",
    description="The event catalogue, including each event's available seats.",
    routers=ROUTERS,
)
