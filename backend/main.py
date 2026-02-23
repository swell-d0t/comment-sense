"""
main.py
-------
FastAPI application entrypoint for CommentSense.
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from db import init_db, check_db_connection
from services.hybrid import load_models, models_are_ready, get_load_error
from routers import analyze, auth, instagram, history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting CommentSense API...")

    # Initialize database tables
    try:
        await init_db()
    except Exception as e:
        logger.critical("Database initialization failed: %s", e)

    # Load ML models
    success = load_models()
    if not success:
        logger.critical("Model loading failed: %s", get_load_error())
    else:
        logger.info("All systems ready.")

    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="CommentSense API",
    description="Hybrid ML Instagram comment sentiment analysis.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

# ── Request ID middleware ─────────────────────────────────────────────────────
@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# ── Request size limit ────────────────────────────────────────────────────────
MAX_REQUEST_BODY_BYTES = 200_000

@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={
                "error": "REQUEST_TOO_LARGE",
                "message": f"Request exceeds {MAX_REQUEST_BODY_BYTES // 1000}KB limit.",
            },
        )
    return await call_next(request)

# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        field = " → ".join(str(loc) for loc in error["loc"] if loc != "body")
        errors.append({"field": field or "request body", "message": error["msg"]})
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "VALIDATION_ERROR", "message": "Invalid request data.", "details": errors},
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception("Unhandled exception on %s (request_id=%s)", request.url.path, request_id)
    expose = os.getenv("EXPOSE_ERROR_DETAILS", "false").lower() == "true"
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
            "request_id": request_id,
            **({"detail": str(exc)} if expose else {}),
        },
    )

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    db_ok = await check_db_connection()
    models_ok = models_are_ready()

    if not models_ok or not db_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "degraded",
                "models_loaded": models_ok,
                "database": db_ok,
                "model_error": get_load_error(),
            },
        )
    return {"status": "healthy", "models_loaded": True, "database": True}

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(analyze.router, prefix="/analyze", tags=["Analysis"])
app.include_router(instagram.router, prefix="/instagram", tags=["Instagram"])
app.include_router(history.router, prefix="/history", tags=["History"])
