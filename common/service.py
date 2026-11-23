"""The shared FastAPI assembly every backend service uses.

Each service lives in its own folder under ``services/`` and is built, imaged and
deployed on its own. What they still share is this: the same database, the same
localized error shape, and the same startup. ``build_app`` is that shared part,
so a service module only has to name its own title, routers and documentation
paths.

They share one SQLite database. That is what keeps the split cheap: every service
resolves a bearer token by reading ``auth_sessions`` itself, and a registration
can still check an event's capacity with a join, so no service ever has to call
another one.
"""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from common.database import initialize_database
from common.messages import APIMessageError, translate_message


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Every service runs this. The statements are all CREATE TABLE IF NOT EXISTS,
    # so three containers starting at once converge on the same schema; the
    # connection's busy timeout absorbs the contention on a first cold start.
    initialize_database()
    yield


def build_app(
    *,
    title: str,
    description: str,
    routers: Iterable[APIRouter],
    docs_url: str,
    openapi_url: str,
    redoc_url: str | None = None,
    swagger_ui_oauth2_redirect_url: str = "/docs/oauth2-redirect",
) -> FastAPI:
    app = FastAPI(
        title=title,
        description=description,
        version="1.0.0",
        lifespan=lifespan,
        docs_url=docs_url,
        openapi_url=openapi_url,
        redoc_url=redoc_url,
        swagger_ui_oauth2_redirect_url=swagger_ui_oauth2_redirect_url,
    )

    @app.exception_handler(APIMessageError)
    async def localize_api_message(
        request: Request, error: APIMessageError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "detail": translate_message(
                    error.message_key,
                    request.headers.get("accept-language"),
                )
            },
            headers=error.headers,
        )

    for router in routers:
        app.include_router(router)
    return app


def build_service(
    *,
    name: str,
    description: str,
    routers: Iterable[APIRouter],
) -> FastAPI:
    """Build one backend service: the app a single container runs.

    The documentation lives under the same path prefix the gateway routes to this
    service, so both the Swagger page and the OpenAPI document it fetches are
    reachable through the one public URL without the gateway rewriting a path.
    The Compose healthchecks poll ``/docs/<name>/openapi.json``, so these paths
    are a contract, not a convenience.
    """
    return build_app(
        title=f"UNIBZ Event Registration - {name}",
        description=description,
        routers=routers,
        docs_url=f"/docs/{name}",
        openapi_url=f"/docs/{name}/openapi.json",
        swagger_ui_oauth2_redirect_url=f"/docs/{name}/oauth2-redirect",
    )
