import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.faq import get_faq
from backend.model_client import ModelClient, UpstreamError, get_model_client
from backend.prompts import load_prompt
from backend.reply import assemble_reply
from backend.schemas import ChatRequest, ChatResponse, Contact, ErrorResponse

logger = logging.getLogger("backend")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_faq()  # a malformed faq.md raises here, so the app refuses to start
    yield


app = FastAPI(title="Cadre FAQ Bot", lifespan=lifespan)


def error_response(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=code, message=message, contact=Contact())
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


def _is_api(request: Request) -> bool:
    return request.url.path == "/api" or request.url.path.startswith("/api/")


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(
        422, "invalid_request", "That message couldn't be processed. Please try again."
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if not _is_api(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if exc.status_code == 404:
        return error_response(404, "not_found", "That page doesn't exist.")
    return error_response(
        exc.status_code,
        "invalid_request",
        "That request isn't supported.",
        headers=dict(exc.headers) if exc.headers else None,
    )


@app.exception_handler(UpstreamError)
async def handle_upstream_error(request: Request, exc: UpstreamError) -> JSONResponse:
    logger.warning("Upstream model error: %s", type(exc).__name__)
    return error_response(
        503,
        "upstream_unavailable",
        "The assistant is temporarily unavailable. Please try again shortly.",
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error", exc_info=exc)
    return error_response(
        500, "internal_error", "Something went wrong on our side. Please try again."
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest, client: Annotated[ModelClient, Depends(get_model_client)]
) -> ChatResponse:
    faq = get_faq()
    result = await client.complete(
        load_prompt(), [m.model_dump() for m in request.history], request.message
    )
    return assemble_reply(result, faq)
