"""
routers/history.py
------------------
Returns the authenticated user's analysis history.
"""

import logging
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.db_models import User, Analysis
from routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
async def get_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """Returns the user's past analyses, newest first."""
    if limit > 100:
        limit = 100

    result = await db.execute(
        select(Analysis)
        .where(Analysis.user_id == user.id)
        .order_by(desc(Analysis.created_at))
        .limit(limit)
        .offset(offset)
    )
    analyses = result.scalars().all()

    return {
        "analyses": [
            {
                "id": a.id,
                "label": a.label,
                "created_at": a.created_at.isoformat(),
                "source": a.source,
                "total_comments": a.total_comments,
                "positive_pct": a.positive_pct,
                "neutral_pct": a.neutral_pct,
                "negative_pct": a.negative_pct,
                "avg_confidence": a.avg_confidence,
                "instagram_post_url": a.instagram_post_url,
            }
            for a in analyses
        ]
    }


@router.get("/{analysis_id}")
async def get_analysis_detail(
    analysis_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the full result for a specific past analysis.
    Enforces ownership — users can only retrieve their own analyses.
    """
    result = await db.execute(
        select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.user_id == user.id,  # ownership check
        )
    )
    analysis = result.scalar_one_or_none()

    if analysis is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "NOT_FOUND", "message": "Analysis not found."}
        )

    return {
        "id": analysis.id,
        "label": analysis.label,
        "created_at": analysis.created_at.isoformat(),
        "source": analysis.source,
        "total_comments": analysis.total_comments,
        "aggregate": {
            "positive_pct": analysis.positive_pct,
            "neutral_pct": analysis.neutral_pct,
            "negative_pct": analysis.negative_pct,
            "avg_confidence": analysis.avg_confidence,
        },
        "full_result": analysis.full_result,
    }


@router.delete("/{analysis_id}")
async def delete_analysis(
    analysis_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deletes a specific analysis. Ownership enforced."""
    result = await db.execute(
        select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.user_id == user.id,
        )
    )
    analysis = result.scalar_one_or_none()

    if analysis is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "NOT_FOUND"}
        )

    await db.delete(analysis)
    await db.commit()
    return {"message": "Analysis deleted."}
