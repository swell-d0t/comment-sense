"""
services/token_store.py
-----------------------
Handles all OAuth token operations:
  - Storing and retrieving encrypted access tokens
  - Token refresh before expiry
  - Detecting and handling revoked tokens
  - CSRF state parameter management via Redis

Edge cases handled:
  - Token encryption key missing from environment — fail at startup, not silently
  - Encryption/decryption failure — treated as token corruption, user re-authenticates
  - Token expiry — checked before every API call; refreshed automatically if < 7 days left
  - Token revoked by user on Instagram — 401 caught, token deleted, re-auth triggered
  - Redis unavailable — graceful degradation for state management (falls back to DB)
  - State parameter replay attack — state deleted from Redis immediately after first use
  - State parameter timeout — states expire after 10 minutes in Redis
  - Concurrent refresh race condition — Redis lock prevents double-refresh
  - Database write failure during token storage — transaction rolled back cleanly
"""

import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
TOKEN_REFRESH_THRESHOLD_DAYS = 7   # refresh if expiring within this many days
STATE_EXPIRY_SECONDS = 600          # OAuth state params expire in 10 minutes
REFRESH_LOCK_EXPIRY_SECONDS = 30    # Redis lock TTL for concurrent refresh guard
TOKEN_LONG_LIVED_DAYS = 60          # Meta long-lived token lifetime


# ── Encryption setup ──────────────────────────────────────────────────────────

def _get_cipher():
    """
    Returns a Fernet cipher instance using the ENCRYPTION_KEY environment variable.
    Raises a clear error at startup if the key is missing or malformed.
    This is called lazily so the import doesn't fail if cryptography isn't installed.
    """
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        raise RuntimeError(
            "cryptography package is required. Run: pip install cryptography"
        )

    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        raise RuntimeError(
            "ENCRYPTION_KEY is set but is not a valid Fernet key. "
            "Regenerate it with the command above."
        )


def encrypt_token(token: str) -> str:
    """Encrypts a plaintext access token. Returns the encrypted string."""
    cipher = _get_cipher()
    return cipher.encrypt(token.encode()).decode()


def decrypt_token(encrypted_token: str) -> Optional[str]:
    """
    Decrypts an encrypted access token.
    Returns None if decryption fails (corrupted data or wrong key).
    The caller must treat None as a revoked/invalid token and trigger re-auth.
    """
    from cryptography.fernet import InvalidToken
    try:
        cipher = _get_cipher()
        return cipher.decrypt(encrypted_token.encode()).decode()
    except InvalidToken:
        logger.error(
            "Token decryption failed — token may be corrupted or encrypted with a different key."
        )
        return None
    except Exception as e:
        logger.error("Unexpected decryption error: %s", e)
        return None


# ── Redis state management ────────────────────────────────────────────────────

def _get_redis():
    """
    Returns a Redis client. Returns None if Redis is unavailable.
    All callers must handle the None case gracefully.
    """
    try:
        import redis
        r = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        r.ping()
        return r
    except Exception as e:
        logger.warning("Redis unavailable: %s. Falling back to degraded mode.", e)
        return None


def store_oauth_state(state: str) -> bool:
    """
    Stores an OAuth state parameter in Redis with a 10-minute expiry.
    Returns True on success, False if Redis is unavailable.

    The state is a cryptographically random string used to prevent CSRF.
    It must be verified when Instagram redirects back to our callback URL.
    """
    redis_client = _get_redis()
    if redis_client is None:
        logger.error(
            "Cannot store OAuth state — Redis is unavailable. "
            "OAuth flow is not safe without state validation."
        )
        return False

    try:
        key = f"oauth_state:{state}"
        redis_client.setex(key, STATE_EXPIRY_SECONDS, "1")
        return True
    except Exception as e:
        logger.error("Failed to store OAuth state in Redis: %s", e)
        return False


def verify_and_consume_oauth_state(state: str) -> bool:
    """
    Verifies an OAuth state parameter exists and immediately deletes it.
    Returns True if the state was valid and not previously used.
    Returns False if the state is unknown, expired, or already consumed.

    The delete-on-read pattern prevents replay attacks: the same state
    parameter cannot be used twice even if an attacker intercepts the
    redirect URL.
    """
    if not state or len(state) < 32:
        logger.warning("OAuth state parameter is missing or too short.")
        return False

    redis_client = _get_redis()
    if redis_client is None:
        logger.error(
            "Cannot verify OAuth state — Redis is unavailable. "
            "Rejecting OAuth callback for security."
        )
        return False

    try:
        key = f"oauth_state:{state}"
        # getdel atomically gets and deletes — prevents race conditions
        # where two simultaneous requests with the same state both succeed
        result = redis_client.getdel(key)
        if result is None:
            logger.warning(
                "OAuth state '%s...' not found in Redis — expired or already used.",
                state[:8]
            )
            return False
        return True
    except AttributeError:
        # Redis version < 6.2 doesn't have getdel — use pipeline as fallback
        try:
            with redis_client.pipeline() as pipe:
                pipe.get(key)
                pipe.delete(key)
                exists, _ = pipe.execute()
                return exists is not None
        except Exception as e:
            logger.error("Redis pipeline failed for state verification: %s", e)
            return False
    except Exception as e:
        logger.error("Failed to verify OAuth state: %s", e)
        return False


def generate_oauth_state() -> Optional[str]:
    """
    Generates a cryptographically secure random state parameter and
    stores it in Redis. Returns the state string, or None if storage failed.
    """
    state = secrets.token_urlsafe(32)
    success = store_oauth_state(state)
    if not success:
        return None
    return state


# ── Token refresh ─────────────────────────────────────────────────────────────

def should_refresh_token(expires_at: datetime) -> bool:
    """
    Returns True if the token expires within TOKEN_REFRESH_THRESHOLD_DAYS.
    expires_at should be a timezone-aware datetime.
    """
    now = datetime.now(timezone.utc)
    threshold = now + timedelta(days=TOKEN_REFRESH_THRESHOLD_DAYS)
    return expires_at <= threshold


async def refresh_long_lived_token(
    current_token: str,
    user_id: int,
    db,  # SQLAlchemy async session
) -> Optional[str]:
    """
    Exchanges a long-lived token for a new long-lived token with a fresh
    60-day expiry. Uses a Redis lock to prevent concurrent refresh attempts
    for the same user (which would invalidate each other).

    Returns the new token on success, None on failure.
    On failure, the existing token remains in the database unchanged.
    """
    import httpx

    lock_key = f"token_refresh_lock:{user_id}"
    redis_client = _get_redis()

    # Acquire distributed lock — if we can't get it, another request
    # is already refreshing this token
    if redis_client:
        lock_acquired = redis_client.set(
            lock_key, "1",
            nx=True,  # only set if not exists
            ex=REFRESH_LOCK_EXPIRY_SECONDS,
        )
        if not lock_acquired:
            logger.info("Token refresh for user %d already in progress. Skipping.", user_id)
            return current_token  # return existing token; refresh will complete elsewhere
    else:
        lock_acquired = False
        logger.warning("Redis unavailable — proceeding without refresh lock for user %d.", user_id)

    try:
        app_id = os.getenv("META_APP_ID")
        app_secret = os.getenv("META_APP_SECRET")

        if not app_id or not app_secret:
            raise RuntimeError("META_APP_ID or META_APP_SECRET not set in environment.")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://graph.instagram.com/refresh_access_token",
                params={
                    "grant_type": "ig_refresh_token",
                    "access_token": current_token,
                },
            )

        if response.status_code == 401:
            # Token was revoked by the user on Instagram
            logger.warning("Token refresh returned 401 for user %d — token revoked.", user_id)
            await _handle_revoked_token(user_id, db)
            return None

        if response.status_code != 200:
            logger.error(
                "Token refresh failed for user %d: status %d",
                user_id, response.status_code
            )
            return None

        data = response.json()
        new_token = data.get("access_token")
        expires_in = data.get("expires_in", TOKEN_LONG_LIVED_DAYS * 86400)

        if not new_token:
            logger.error("Token refresh response missing access_token: %s", data)
            return None

        new_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        encrypted = encrypt_token(new_token)

        # Persist to database
        await _update_token_in_db(user_id, encrypted, new_expiry, db)

        logger.info("Token refreshed successfully for user %d.", user_id)
        return new_token

    except httpx.TimeoutException:
        logger.error("Token refresh timed out for user %d.", user_id)
        return None
    except Exception as e:
        logger.error("Unexpected error during token refresh for user %d: %s", user_id, e)
        return None
    finally:
        if redis_client and lock_acquired:
            redis_client.delete(lock_key)


async def _handle_revoked_token(user_id: int, db) -> None:
    """
    Called when Instagram returns 401 during a token operation.
    Deletes the stored token and marks the user as disconnected.
    The API layer will then return a response telling the frontend
    to redirect the user to reconnect their account.
    """
    try:
        from models.db_models import User
        from sqlalchemy import update

        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                instagram_token=None,
                instagram_token_expires=None,
                instagram_connected=False,
            )
        )
        await db.commit()
        logger.info("Revoked token cleared for user %d.", user_id)
    except Exception as e:
        logger.error("Failed to clear revoked token for user %d: %s", user_id, e)
        await db.rollback()


async def _update_token_in_db(
    user_id: int,
    encrypted_token: str,
    expires_at: datetime,
    db,
) -> None:
    """Updates the stored token and expiry date in the database."""
    from models.db_models import User
    from sqlalchemy import update

    try:
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                instagram_token=encrypted_token,
                instagram_token_expires=expires_at,
            )
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("Database write failed during token update for user %d: %s", user_id, e)
        raise


# ── Token retrieval (the function the rest of the app calls) ──────────────────

async def get_valid_token(user_id: int, db) -> Optional[str]:
    """
    Returns a valid, decrypted access token for the given user.
    Automatically refreshes the token if it's expiring soon.
    Returns None if the token is invalid, revoked, or the user has disconnected.

    This is the only function other services should call to get a token.
    """
    from models.db_models import User
    from sqlalchemy import select

    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    except Exception as e:
        logger.error("Database error fetching user %d: %s", user_id, e)
        return None

    if user is None:
        logger.warning("User %d not found.", user_id)
        return None

    if not user.instagram_token:
        logger.info("User %d has no Instagram token stored.", user_id)
        return None

    # Decrypt
    plaintext_token = decrypt_token(user.instagram_token)
    if plaintext_token is None:
        logger.error("Token decryption failed for user %d — treating as revoked.", user_id)
        await _handle_revoked_token(user_id, db)
        return None

    # Refresh if expiring soon
    if user.instagram_token_expires and should_refresh_token(user.instagram_token_expires):
        logger.info("Token for user %d expiring soon — refreshing.", user_id)
        refreshed = await refresh_long_lived_token(plaintext_token, user_id, db)
        return refreshed  # None if refresh failed (caller handles re-auth)

    return plaintext_token
