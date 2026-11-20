import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Receive, Scope, Send

from backend.chat import handle_chat
from backend.faq import get_faq
from backend.model_client import (
    ModelClient,
    UpstreamError,
    get_model_client,
    required_env,
)
from backend.prompts import prompt_version
from backend.schemas import ChatRequest, ChatResponse, Contact, ErrorResponse

logger = logging.getLogger("backend")

DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    required_env("OPENROUTER_API_KEY")  # a missing variable stops the app
    required_env("OPENROUTER_MODEL")
    get_faq()  # a malformed faq.md raises here, so the app refuses to start
    yield


app = FastAPI(title="Cadre FAQ Bot", lifespan=lifespan)


def error_response(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=code, message=message, contact=Contact())
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _is_api(request: Request) -> bool:
    return _is_api_path(request.url.path)


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
async def health() -> dict[str, str | int]:
    return {
        "status": "ok",
        "prompt_version": prompt_version(),
        "faq_entries": len(get_faq().entries),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest, client: Annotated[ModelClient, Depends(get_model_client)]
) -> ChatResponse:
    reply, _ = await handle_chat(request, client)
    return reply


def _frontend_dist() -> Path:
    configured = os.environ.get("FRONTEND_DIST")
    return Path(configured) if configured else DEFAULT_FRONTEND_DIST


def _serve_frontend(dist: Path) -> None:
    """Serve the built frontend with SPA fallback, if a build is present.

    This replaces the router's no-match handler rather than adding a catch-all
    route, so real /api routes (and their 405s) always win, and unknown /api
    paths still get the JSON 404.
    """
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        return

    async def default(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            raise StarletteHTTPException(404)
        path = scope["path"]
        if scope["method"] not in ("GET", "HEAD") or _is_api_path(path):
            raise StarletteHTTPException(404)
        relative = path.lstrip("/")
        if "\x00" in relative:  # a decoded %00 would make resolve() raise
            raise StarletteHTTPException(404)
        candidate = (root / relative).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            response = FileResponse(candidate)
        elif Path(relative).suffix:  # a missing asset is a 404, not the app shell
            raise StarletteHTTPException(404)
        else:
            response = FileResponse(index)
        await response(scope, receive, send)

    app.router.default = default


_serve_frontend(_frontend_dist())
