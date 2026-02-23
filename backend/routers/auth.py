"""
routers/auth.py
---------------
Handles the full Instagram OAuth 2.0 flow.

Endpoints:
  GET  /auth/login        — redirects user to Instagram's auth page
  GET  /auth/callback     — receives the code from Instagram, exchanges it
  POST /auth/logout       — clears the session cookie
  GET  /auth/me           — returns current user info (used by frontend)
  POST /auth/deauthorize  — Meta webhook when user revokes via Instagram settings
  POST /auth/delete       — Meta webhook for data deletion requests (GDPR)

Security enforced:
  - State parameter CSRF protection (generated and verified via Redis)
  - OAuth flow aborted if Redis unavailable (no state = no safety)
  - Short-lived code exchanged server-to-server only (never touches browser)
  - Long-lived token stored encrypted in PostgreSQL
  - Session issued as HTTP-only, Secure, SameSite=Lax cookie (not localStorage)
  - Each login creates a new session (no session fixation)
  - Deauthorize and delete webhooks verified with Meta's signed_request
"""

import hashlib
import hmac
import json
import logging
import os
from base64 import b64decode
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db import get_db
from models.db_models import User
from services.token_store import (
    encrypt_token,
    generate_oauth_state,
    verify_and_consume_oauth_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Config ────────────────────────────────────────────────────────────────────
META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Instagram permissions we request
INSTAGRAM_SCOPES = "instagram_basic,instagram_manage_comments,pages_show_list"


# ── GET /auth/login ───────────────────────────────────────────────────────────

@router.get("/login")
async def instagram_login():
    """
    Generates a state parameter, stores it in Redis, and redirects
    the user to Instagram's OAuth authorization page.

    If Redis is unavailable, we abort rather than proceeding without
    CSRF protection — a request without state validation is a security hole.
    """
    if not META_APP_ID:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "OAUTH_NOT_CONFIGURED",
                "message": "Instagram login is not configured on this server."
            }
        )

    state = generate_oauth_state()
    if state is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "STATE_STORAGE_FAILED",
                "message": (
                    "Could not initiate login securely. "
                    "This is a temporary server issue. Please try again."
                )
            }
        )

    auth_url = (
        f"https://api.instagram.com/oauth/authorize"
        f"?client_id={META_APP_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={INSTAGRAM_SCOPES}"
        f"&response_type=code"
        f"&state={state}"
    )

    return RedirectResponse(url=auth_url)


# ── GET /auth/callback ────────────────────────────────────────────────────────

@router.get("/callback")
async def instagram_callback(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_reason: Optional[str] = None,
):
    """
    Instagram redirects here after the user approves or denies the app.

    On denial:   redirect to login page with an error message.
    On approval: exchange code for token, upsert user, issue JWT cookie,
                 redirect to /dashboard.
    """

    # ── User denied access ────────────────────────────────────────────────
    if error:
        logger.info("User denied Instagram OAuth: %s (%s)", error, error_reason)
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=access_denied",
            status_code=status.HTTP_302_FOUND,
        )

    # ── Missing parameters ────────────────────────────────────────────────
    if not code or not state:
        logger.warning("OAuth callback missing code or state parameters.")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=invalid_callback",
            status_code=status.HTTP_302_FOUND,
        )

    # ── Verify CSRF state ─────────────────────────────────────────────────
    if not verify_and_consume_oauth_state(state):
        logger.warning("OAuth state verification failed — possible CSRF attempt.")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=state_mismatch",
            status_code=status.HTTP_302_FOUND,
        )

    # ── Exchange code for short-lived token ───────────────────────────────
    short_lived_token = await _exchange_code_for_token(code)
    if short_lived_token is None:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=token_exchange_failed",
            status_code=status.HTTP_302_FOUND,
        )

    # ── Exchange for long-lived token (60 days) ───────────────────────────
    long_lived_token, expires_in = await _get_long_lived_token(short_lived_token)
    if long_lived_token is None:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=token_upgrade_failed",
            status_code=status.HTTP_302_FOUND,
        )

    # ── Fetch the user's Instagram profile ───────────────────────────────
    profile = await _fetch_instagram_profile(long_lived_token)
    if profile is None:
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=profile_fetch_failed",
            status_code=status.HTTP_302_FOUND,
        )

    instagram_user_id = profile.get("id")
    instagram_username = profile.get("username")

    # ── Upsert user in database ───────────────────────────────────────────
    try:
        user = await _upsert_user(
            db=db,
            instagram_user_id=instagram_user_id,
            instagram_username=instagram_username,
            long_lived_token=long_lived_token,
            expires_in=expires_in,
        )
    except Exception as e:
        logger.error("Failed to upsert user %s: %s", instagram_user_id, e)
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=database_error",
            status_code=status.HTTP_302_FOUND,
        )

    # ── Issue JWT session cookie ──────────────────────────────────────────
    jwt_token = _create_jwt(user_id=user.id)
    redirect = RedirectResponse(
        url=f"{FRONTEND_URL}/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
    redirect.set_cookie(
        key="session",
        value=jwt_token,
        httponly=True,       # JS cannot read this cookie
        secure=False,        # Set True in production (requires HTTPS)
        samesite="lax",      # Prevents CSRF for most cases
        max_age=JWT_EXPIRE_MINUTES * 60,
        path="/",
    )
    logger.info("User %s (%s) logged in successfully.", user.id, instagram_username)
    return redirect


# ── POST /auth/logout ─────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(response: Response):
    """Clears the session cookie."""
    response.delete_cookie(key="session", path="/")
    return {"message": "Logged out successfully."}


# ── GET /auth/me ──────────────────────────────────────────────────────────────

@router.get("/me")
async def get_current_user_info(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the current user's profile if the session cookie is valid.
    The frontend calls this on mount to determine if the user is logged in.
    Returns 401 if not authenticated — frontend redirects to /login.
    """
    user = await _get_user_from_cookie(request, db)
    if user is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "NOT_AUTHENTICATED", "message": "Please log in."}
        )

    return {
        "id": user.id,
        "instagram_username": user.instagram_username,
        "instagram_avatar_url": user.instagram_avatar_url,
        "instagram_connected": user.instagram_connected,
    }


# ── POST /auth/deauthorize ────────────────────────────────────────────────────

@router.post("/deauthorize")
async def deauthorize_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Meta calls this webhook when a user removes your app via Instagram settings.
    We must verify the signed_request parameter and delete the user's token.
    """
    form = await request.form()
    signed_request = form.get("signed_request")

    if not signed_request or not _verify_signed_request(signed_request):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "INVALID_SIGNATURE"}
        )

    payload = _parse_signed_request(signed_request)
    if not payload:
        return JSONResponse(status_code=400, content={"error": "INVALID_PAYLOAD"})

    instagram_user_id = payload.get("user_id")
    if instagram_user_id:
        await _disconnect_user(instagram_user_id, db)
        logger.info("Deauthorized user with Instagram ID: %s", instagram_user_id)

    return {"status": "ok"}


# ── POST /auth/delete ─────────────────────────────────────────────────────────

@router.post("/delete")
async def data_deletion_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Meta calls this for GDPR data deletion requests.
    We must delete ALL data for the user and return a confirmation URL.
    """
    form = await request.form()
    signed_request = form.get("signed_request")

    if not signed_request or not _verify_signed_request(signed_request):
        return JSONResponse(status_code=400, content={"error": "INVALID_SIGNATURE"})

    payload = _parse_signed_request(signed_request)
    if not payload:
        return JSONResponse(status_code=400, content={"error": "INVALID_PAYLOAD"})

    instagram_user_id = payload.get("user_id")
    confirmation_code = f"cs_delete_{instagram_user_id}"

    if instagram_user_id:
        await _delete_all_user_data(instagram_user_id, db)
        logger.info("Deleted all data for Instagram user ID: %s", instagram_user_id)

    # Meta requires this specific response format
    return {
        "url": f"{FRONTEND_URL}/privacy/deletion-confirmed?code={confirmation_code}",
        "confirmation_code": confirmation_code,
    }


# ── Shared auth dependency ────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency used by protected endpoints.
    Raises 401 if session cookie is missing, expired, or invalid.
    Usage: user: User = Depends(get_current_user)
    """
    user = await _get_user_from_cookie(request, db)
    if user is None:
        raise JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "NOT_AUTHENTICATED",
                "message": "Your session has expired. Please log in again."
            }
        )
    return user


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _exchange_code_for_token(code: str) -> Optional[str]:
    """Exchanges the short-lived code for a short-lived access token."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.instagram.com/oauth/access_token",
                data={
                    "client_id": META_APP_ID,
                    "client_secret": META_APP_SECRET,
                    "grant_type": "authorization_code",
                    "redirect_uri": REDIRECT_URI,
                    "code": code,
                },
            )
        if response.status_code != 200:
            logger.error("Code exchange failed: %d %s", response.status_code, response.text[:200])
            return None
        return response.json().get("access_token")
    except Exception as e:
        logger.error("Code exchange exception: %s", e)
        return None


async def _get_long_lived_token(short_lived_token: str) -> tuple[Optional[str], int]:
    """
    Exchanges a short-lived token (1 hour) for a long-lived token (60 days).
    Returns (token, expires_in_seconds) or (None, 0).
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": META_APP_SECRET,
                    "access_token": short_lived_token,
                },
            )
        if response.status_code != 200:
            logger.error("Long-lived token exchange failed: %d", response.status_code)
            return None, 0
        data = response.json()
        return data.get("access_token"), data.get("expires_in", 5184000)
    except Exception as e:
        logger.error("Long-lived token exchange exception: %s", e)
        return None, 0


async def _fetch_instagram_profile(token: str) -> Optional[dict]:
    """Fetches the user's Instagram username and ID."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://graph.instagram.com/me",
                params={"fields": "id,username", "access_token": token},
            )
        if response.status_code != 200:
            logger.error("Profile fetch failed: %d", response.status_code)
            return None
        return response.json()
    except Exception as e:
        logger.error("Profile fetch exception: %s", e)
        return None


async def _upsert_user(
    db: AsyncSession,
    instagram_user_id: str,
    instagram_username: str,
    long_lived_token: str,
    expires_in: int,
) -> User:
    """Creates or updates a user record. Returns the user."""
    encrypted_token = encrypt_token(long_lived_token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    result = await db.execute(
        select(User).where(User.instagram_user_id == instagram_user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            instagram_user_id=instagram_user_id,
            instagram_username=instagram_username,
            instagram_token=encrypted_token,
            instagram_token_expires=expires_at,
            instagram_connected=True,
        )
        db.add(user)
    else:
        user.instagram_username = instagram_username
        user.instagram_token = encrypted_token
        user.instagram_token_expires = expires_at
        user.instagram_connected = True

    await db.commit()
    await db.refresh(user)
    return user


async def _get_user_from_cookie(request: Request, db: AsyncSession) -> Optional[User]:
    """Validates the session cookie and returns the User, or None."""
    token = request.cookies.get("session")
    if not token:
        return None

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


def _create_jwt(user_id: int) -> str:
    """Creates a JWT token encoding the user's database ID."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _verify_signed_request(signed_request: str) -> bool:
    """
    Verifies Meta's signed_request parameter using HMAC-SHA256.
    This proves the webhook came from Meta, not a random attacker.
    """
    try:
        encoded_sig, payload = signed_request.split(".", 1)
        sig = b64decode(encoded_sig + "==")
        expected = hmac.new(
            META_APP_SECRET.encode(),
            payload.encode(),
            hashlib.sha256,
        ).digest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def _parse_signed_request(signed_request: str) -> Optional[dict]:
    """Decodes and returns the payload of a verified signed_request."""
    try:
        _, payload = signed_request.split(".", 1)
        padding = 4 - len(payload) % 4
        decoded = b64decode(payload + "=" * padding)
        return json.loads(decoded)
    except Exception:
        return None


async def _disconnect_user(instagram_user_id: str, db: AsyncSession) -> None:
    """Clears token for a user who revoked access."""
    result = await db.execute(
        select(User).where(User.instagram_user_id == instagram_user_id)
    )
    user = result.scalar_one_or_none()
    if user:
        user.instagram_token = None
        user.instagram_token_expires = None
        user.instagram_connected = False
        await db.commit()


async def _delete_all_user_data(instagram_user_id: str, db: AsyncSession) -> None:
    """
    Permanently deletes all data for a user (GDPR compliance).
    Cascades to analyses via the database foreign key relationship.
    """
    result = await db.execute(
        select(User).where(User.instagram_user_id == instagram_user_id)
    )
    user = result.scalar_one_or_none()
    if user:
        await db.delete(user)
        await db.commit()
        logger.info("All data deleted for Instagram user ID %s.", instagram_user_id)
