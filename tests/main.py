"""
main.py
-------
FastAPI application entrypoint. Handles:
  - Application lifespan (model loading on startup)
  - CORS configuration
  - Rate limiting
  - Global exception handlers
  - Health check endpoint

Edge cases handled at the API layer:
  - Models fail to load at startup — server returns 503 on all /analyze calls
  - Request body exceeds size limit — 413 before any processing
  - Malformed JSON — FastAPI returns 422 automatically; we customize the response
  - Validation errors from Pydantic — formatted into user-readable messages
  - Unhandled exceptions — caught globally, logged, returned as 500 with trace ID
  - CORS — locked to allowed origins only
  - Rate limiting — per-IP with clear error messages
  - Request ID — every request gets a UUID for traceability in logs
"""

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from services.hybrid import load_models, models_are_ready, get_load_error
from routers import analyze, auth, instagram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


# ── Lifespan: model loading and teardown ─────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on startup and once on shutdown.
    Models are loaded here so they live in memory for the full server lifetime.
    If loading fails, the server starts but returns 503 on inference endpoints
    rather than crashing entirely (allows health checks to still respond).
    """
    logger.info("Server starting up. Loading ML models...")
    success = load_models()
    if not success:
        logger.critical(
            "Model loading failed: %s. "
            "Server is up but /analyze endpoints will return 503.",
            get_load_error()
        )
    else:
        logger.info("Models ready. Server accepting requests.")
    yield
    logger.info("Server shutting down.")


# ── App initialization ────────────────────────────────────────────────────────

app = FastAPI(
    title="CommentSense API",
    description="Hybrid ML sentiment analysis for Instagram comments.",
    version="1.0.0",
    lifespan=lifespan,
    # Disable default /docs redirect — we'll keep docs but be explicit
    docs_url="/docs",
    redoc_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── CORS ──────────────────────────────────────────────────────────────────────
# In production, replace localhost:3000 with your actual frontend domain.
# Never use allow_origins=["*"] in production — it allows any website
# to make requests to your API using a logged-in user's credentials.

import os
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,   # required for cookies (OAuth session)
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)


# ── Request ID middleware ─────────────────────────────────────────────────────

@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """
    Attaches a unique request ID to every request. This ID appears in:
      - The response header (X-Request-ID)
      - All log lines for this request
    This makes it possible to trace a specific request across logs.
    """
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── Request size limit middleware ─────────────────────────────────────────────

MAX_REQUEST_BODY_BYTES = 200_000  # ~200KB; generous for 50k chars of text

@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    """
    Rejects requests whose body exceeds MAX_REQUEST_BODY_BYTES before
    any parsing or processing occurs. Without this, a malicious client
    could send a gigabyte request and consume all server memory.
    """
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={
                "error": "REQUEST_TOO_LARGE",
                "message": (
                    f"Request body exceeds the {MAX_REQUEST_BODY_BYTES // 1000}KB limit. "
                    "Please reduce the amount of text per request."
                ),
            },
        )
    return await call_next(request)


# ── Global exception handlers ─────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    FastAPI raises RequestValidationError when the request body doesn't
    match the Pydantic schema. The default response is hard to read.
    This handler formats it into clear, user-facing messages.
    """
    errors = []
    for error in exc.errors():
        field = " → ".join(str(loc) for loc in error["loc"] if loc != "body")
        errors.append({
            "field": field or "request body",
            "message": error["msg"],
        })

    logger.warning(
        "Validation error on %s: %s",
        request.url.path,
        errors,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "VALIDATION_ERROR",
            "message": "The request data was invalid.",
            "details": errors,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catches any unhandled exception. Logs it with the request ID for
    traceability, and returns a generic 500 without leaking internal details
    to the client. In development, you can set EXPOSE_ERROR_DETAILS=true
    to see the actual exception in the response.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception(
        "Unhandled exception on %s (request_id=%s)",
        request.url.path,
        request_id,
    )

    expose_details = os.getenv("EXPOSE_ERROR_DETAILS", "false").lower() == "true"

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred. Please try again.",
            "request_id": request_id,
            **({"detail": str(exc)} if expose_details else {}),
        },
    )


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    """
    Returns 200 if the server is running and models are loaded.
    Returns 503 if models failed to load.
    Used by load balancers and uptime monitors.
    """
    if not models_are_ready():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "degraded",
                "models_loaded": False,
                "error": get_load_error(),
            },
        )
    return {
        "status": "healthy",
        "models_loaded": True,
    }


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(analyze.router, prefix="/analyze", tags=["Analysis"])
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(instagram.router, prefix="/instagram", tags=["Instagram"])
