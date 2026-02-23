"""
routers/instagram.py
--------------------
Fetches data from the Instagram Graph API on behalf of the authenticated user.

CRITICAL OWNERSHIP ENFORCEMENT:
Every endpoint here calls get_current_user() which validates the session cookie.
When fetching posts, we ONLY return posts belonging to the authenticated user's
Instagram account — the one they connected via OAuth. There is no way to
query another user's posts through this API.

When fetching comments on a specific post, we first verify that the post
belongs to the authenticated user before making any API calls. If it doesn't,
we return 403. This prevents any scenario where a user could manipulate the
post ID parameter to analyze someone else's comments.

Endpoints:
  GET /instagram/posts           — list the user's own Instagram posts
  GET /instagram/posts/{post_id}/comments — fetch comments on one of their posts
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.db_models import User
from routers.auth import get_current_user
from services.token_store import get_valid_token

logger = logging.getLogger(__name__)
router = APIRouter()

# Max comments to fetch per post (pagination stops here)
MAX_COMMENTS_TO_FETCH = 500
INSTAGRAM_API_BASE = "https://graph.instagram.com"


# ── GET /instagram/posts ──────────────────────────────────────────────────────

@router.get("/posts")
async def get_my_posts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the authenticated user's Instagram posts.
    Only returns posts for the currently logged-in user's account.
    """
    token = await get_valid_token(user.id, db)
    if token is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "TOKEN_INVALID",
                "message": (
                    "Your Instagram connection has expired or been revoked. "
                    "Please reconnect your account."
                )
            }
        )

    posts, error = await _fetch_user_posts(token)
    if error:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "INSTAGRAM_API_ERROR", "message": error}
        )

    return {"posts": posts, "count": len(posts)}


# ── GET /instagram/posts/{post_id}/comments ───────────────────────────────────

@router.get("/posts/{post_id}/comments")
async def get_post_comments(
    post_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetches comments for a specific Instagram post.

    OWNERSHIP CHECK: Before fetching any comments, we verify this post
    belongs to the authenticated user. If it doesn't, we return 403.
    This is the core safeguard against analyzing someone else's content.

    post_id must be a numeric Instagram post ID (e.g. "17854360229135492").
    We validate its format to prevent injection attempts.
    """

    # ── Validate post_id format ───────────────────────────────────────────
    if not post_id.isdigit() or len(post_id) > 30:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "INVALID_POST_ID", "message": "Invalid post ID format."}
        )

    token = await get_valid_token(user.id, db)
    if token is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "TOKEN_INVALID",
                "message": "Your Instagram connection has expired. Please reconnect."
            }
        )

    # ── OWNERSHIP VERIFICATION ────────────────────────────────────────────
    # Fetch the post's owner ID from Instagram's API.
    # This is the definitive check — Instagram itself tells us who owns the post.
    ownership_verified, ownership_error = await _verify_post_ownership(
        post_id=post_id,
        instagram_user_id=user.instagram_user_id,
        token=token,
    )

    if ownership_error == "NOT_FOUND":
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "POST_NOT_FOUND",
                "message": "This post does not exist or is not accessible."
            }
        )

    if ownership_error == "API_ERROR":
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": "INSTAGRAM_API_ERROR",
                "message": "Could not verify post ownership. Please try again."
            }
        )

    if not ownership_verified:
        # This is not an error the user should investigate — just a clear denial.
        logger.warning(
            "User %d (Instagram ID: %s) attempted to access post %s which they don't own.",
            user.id, user.instagram_user_id, post_id
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": "NOT_YOUR_POST",
                "message": (
                    "You can only analyze comments on your own Instagram posts. "
                    "This post belongs to a different account."
                )
            }
        )

    # ── Fetch comments (ownership confirmed) ─────────────────────────────
    comments, fetch_error = await _fetch_post_comments(post_id, token)

    if fetch_error:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"error": "INSTAGRAM_API_ERROR", "message": fetch_error}
        )

    return {
        "post_id": post_id,
        "comment_count": len(comments),
        "comments": comments,
        "truncated": len(comments) == MAX_COMMENTS_TO_FETCH,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_user_posts(token: str) -> tuple[list[dict], Optional[str]]:
    """
    Fetches the authenticated user's media posts.
    Returns (posts_list, error_message_or_None).
    """
    posts = []
    url = f"{INSTAGRAM_API_BASE}/me/media"
    params = {
        "fields": "id,caption,media_type,media_url,thumbnail_url,timestamp,comments_count,permalink",
        "access_token": token,
        "limit": 50,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            while url:
                response = await client.get(url, params=params)

                if response.status_code == 401:
                    return [], "Your Instagram access has been revoked. Please reconnect."

                if response.status_code != 200:
                    logger.error("Posts fetch failed: status=%d", response.status_code)
                    return [], "Instagram returned an error. Please try again."

                data = response.json()
                batch = data.get("data", [])

                # Filter to only IMAGE and VIDEO posts (not STORY, CAROUSEL_ALBUM sub-items)
                for post in batch:
                    if post.get("media_type") in ("IMAGE", "VIDEO", "CAROUSEL_ALBUM"):
                        posts.append({
                            "id": post["id"],
                            "caption": (post.get("caption") or "")[:150],
                            "media_type": post.get("media_type"),
                            "thumbnail_url": post.get("thumbnail_url") or post.get("media_url"),
                            "timestamp": post.get("timestamp"),
                            "comments_count": post.get("comments_count", 0),
                            "permalink": post.get("permalink"),
                        })

                # Follow pagination cursor
                paging = data.get("paging", {})
                next_url = paging.get("next")
                if next_url and len(posts) < 100:
                    url = next_url
                    params = {}  # params are embedded in the next URL
                else:
                    url = None

        return posts, None

    except httpx.TimeoutException:
        return [], "Request to Instagram timed out. Please try again."
    except Exception as e:
        logger.error("Unexpected error fetching posts: %s", e)
        return [], "An unexpected error occurred while fetching your posts."


async def _verify_post_ownership(
    post_id: str,
    instagram_user_id: str,
    token: str,
) -> tuple[bool, Optional[str]]:
    """
    Verifies a post belongs to the authenticated user by querying Instagram.
    Returns (is_owner: bool, error_code: Optional[str]).

    error_code is None on success, "NOT_FOUND" if the post doesn't exist,
    "API_ERROR" if the request failed unexpectedly.

    This is the security-critical check. We ask Instagram's API:
    "Who owns post {post_id}?" and compare the answer to our user's ID.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{INSTAGRAM_API_BASE}/{post_id}",
                params={
                    "fields": "id,owner",
                    "access_token": token,
                },
            )

        if response.status_code == 404:
            return False, "NOT_FOUND"

        if response.status_code == 401:
            return False, "API_ERROR"

        if response.status_code != 200:
            logger.error(
                "Ownership check failed for post %s: status=%d",
                post_id, response.status_code
            )
            return False, "API_ERROR"

        data = response.json()
        owner_id = data.get("owner", {}).get("id")

        if not owner_id:
            # API didn't return owner — this happens for posts not in the user's
            # own media. Treat as not owned.
            return False, None

        return owner_id == instagram_user_id, None

    except httpx.TimeoutException:
        return False, "API_ERROR"
    except Exception as e:
        logger.error("Unexpected error during ownership check for post %s: %s", post_id, e)
        return False, "API_ERROR"


async def _fetch_post_comments(
    post_id: str,
    token: str,
) -> tuple[list[str], Optional[str]]:
    """
    Fetches all comments for a post, following pagination cursors.
    Returns a flat list of comment text strings (no usernames/metadata).
    Stops after MAX_COMMENTS_TO_FETCH.
    """
    comments = []
    url = f"{INSTAGRAM_API_BASE}/{post_id}/comments"
    params = {
        "fields": "text,timestamp",
        "access_token": token,
        "limit": 50,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            while url and len(comments) < MAX_COMMENTS_TO_FETCH:
                response = await client.get(url, params=params)

                if response.status_code == 401:
                    return [], "Instagram access revoked. Please reconnect your account."

                if response.status_code == 400:
                    # This can happen if comments are disabled on the post
                    logger.info("Comments disabled or unavailable for post %s.", post_id)
                    return [], "Comments are disabled or unavailable for this post."

                if response.status_code != 200:
                    logger.error(
                        "Comment fetch failed for post %s: %d",
                        post_id, response.status_code
                    )
                    return [], "Instagram returned an error while fetching comments."

                data = response.json()

                for comment in data.get("data", []):
                    text = comment.get("text", "").strip()
                    if text:
                        comments.append(text)

                paging = data.get("paging", {})
                next_url = paging.get("next")
                url = next_url if next_url else None
                params = {}  # next URL includes all params

        return comments, None

    except httpx.TimeoutException:
        return [], "Request to Instagram timed out while fetching comments."
    except Exception as e:
        logger.error("Unexpected error fetching comments for post %s: %s", post_id, e)
        return [], "An unexpected error occurred while fetching comments."
