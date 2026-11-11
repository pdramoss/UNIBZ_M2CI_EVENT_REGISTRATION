from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.routes import router
from app.core.database import initialize_database
from app.core.messages import APIMessageError, translate_message


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(
    title="UNIBZ Event Registration API",
    description="Manage users, events, and event registrations from the API or terminal.",
    version="1.0.0",
    lifespan=lifespan,
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


app.include_router(router)
