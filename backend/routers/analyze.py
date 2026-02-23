"""
routers/analyze.py
------------------
Sentiment analysis endpoints. Authentication required on all routes.
Saves every analysis to the database for history/replay.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.db_models import User, Analysis
from routers.auth import get_current_user
from services.parser import parse_instagram_comments, extract_comment_metadata, ParseError
from services.hybrid import analyze_comments, models_are_ready, get_load_error

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class AnalysisOptions(BaseModel):
    vader_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    roberta_weight: float = Field(default=0.65, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def normalize_weights(self) -> "AnalysisOptions":
        total = self.vader_weight + self.roberta_weight
        if total == 0:
            self.vader_weight = 0.35
            self.roberta_weight = 0.65
        elif abs(total - 1.0) > 0.001:
            self.vader_weight = self.vader_weight / total
            self.roberta_weight = self.roberta_weight / total
        return self


class AnalyzeRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)
    raw_text: str = Field(..., min_length=1, max_length=50_000)
    instagram_post_id: Optional[str] = Field(default=None, max_length=30)
    instagram_post_url: Optional[str] = Field(default=None, max_length=512)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)


class BatchPost(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)
    raw_text: str = Field(..., min_length=1, max_length=50_000)


class BatchAnalyzeRequest(BaseModel):
    posts: list[BatchPost] = Field(..., min_length=1, max_length=20)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)


@router.post("")
@limiter.limit("10/minute")
async def analyze_single(
    request: Request,
    body: AnalyzeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not models_are_ready():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "MODELS_NOT_READY",
                "message": "Sentiment models are loading. Please try again in a moment.",
            }
        )

    result = _run_analysis(body.raw_text, body.label, body.options.vader_weight, body.options.roberta_weight)
    if isinstance(result, JSONResponse):
        return result

    await _save_analysis(db, user.id, result, "paste", body.instagram_post_id, body.instagram_post_url)
    return result


@router.post("/batch")
@limiter.limit("5/minute")
async def analyze_batch(
    request: Request,
    body: BatchAnalyzeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not models_are_ready():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "MODELS_NOT_READY", "message": "Models are not ready."}
        )

    labels = [p.label for p in body.posts if p.label]
    batch_warnings = []
    duplicates = list(set(l for l in labels if labels.count(l) > 1))
    if duplicates:
        batch_warnings.append(f"Duplicate labels detected: {duplicates}.")

    results, failed_posts = [], []
    for post in body.posts:
        try:
            result = _run_analysis(post.raw_text, post.label, body.options.vader_weight, body.options.roberta_weight)
            if isinstance(result, JSONResponse):
                failed_posts.append({"label": post.label or "Unlabeled", "error": "Analysis failed"})
            else:
                results.append(result)
                await _save_analysis(db, user.id, result, "paste")
        except Exception as e:
            logger.error("Batch post error '%s': %s", post.label, e)
            failed_posts.append({"label": post.label or "Unlabeled", "error": "Unexpected error"})

    if not results:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "ALL_POSTS_FAILED", "failed_posts": failed_posts}
        )

    return {
        "results": results,
        "comparison": _build_comparison(results),
        "batch_warnings": batch_warnings,
        "failed_posts": failed_posts,
    }


def _run_analysis(raw_text, label, vader_weight, roberta_weight):
    parse_result = parse_instagram_comments(raw_text)
    if isinstance(parse_result, ParseError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": parse_result.code, "message": parse_result.message}
        )

    comments = parse_result.comments
    metadata_list = [extract_comment_metadata(c) for c in comments]
    pipeline_result = analyze_comments(comments, metadata_list, vader_weight, roberta_weight)

    sentiments = pipeline_result.sentiments
    total = len(sentiments)
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    confidence_sum = 0.0
    non_english_count = 0

    for s in sentiments:
        counts[s.sentiment] += 1
        confidence_sum += s.confidence
        if any(f.startswith("non_english") for f in s.flags):
            non_english_count += 1

    avg_confidence = round(confidence_sum / total, 4) if total > 0 else 0.0
    sorted_pos = sorted([s for s in sentiments if s.sentiment == "positive"], key=lambda x: x.confidence, reverse=True)
    sorted_neg = sorted([s for s in sentiments if s.sentiment == "negative"], key=lambda x: x.confidence, reverse=True)

    warnings = list(parse_result.warnings)
    if pipeline_result.model_load_warning:
        warnings.append(pipeline_result.model_load_warning)
    if non_english_count > 0:
        warnings.append(f"{non_english_count} comment(s) may be non-English — accuracy may be reduced.")

    return {
        "id": str(uuid.uuid4()),
        "label": label,
        "total_comments": total,
        "parse_stats": {
            "lines_processed": parse_result.lines_processed,
            "lines_dropped": parse_result.lines_dropped,
            "truncated_comments": parse_result.truncated_comments,
        },
        "aggregate": {
            "positive_pct": round(counts["positive"] / total * 100, 1) if total else 0,
            "neutral_pct": round(counts["neutral"] / total * 100, 1) if total else 0,
            "negative_pct": round(counts["negative"] / total * 100, 1) if total else 0,
            "avg_confidence": avg_confidence,
            "positive_count": counts["positive"],
            "neutral_count": counts["neutral"],
            "negative_count": counts["negative"],
        },
        "comments": [
            {
                "id": f"c_{i:04d}",
                "text": s.text,
                "sentiment": s.sentiment,
                "confidence": s.confidence,
                "vader_compound": s.vader_compound,
                "roberta_scores": s.roberta_scores,
                "flags": s.flags,
            }
            for i, s in enumerate(sentiments)
        ],
        "top_positive": [s.text for s in sorted_pos[:3]],
        "top_negative": [s.text for s in sorted_neg[:3]],
        "warnings": warnings,
    }


async def _save_analysis(db, user_id, result, source, instagram_post_id=None, instagram_post_url=None):
    try:
        agg = result.get("aggregate", {})
        analysis = Analysis(
            user_id=user_id,
            label=result.get("label"),
            source=source,
            instagram_post_id=instagram_post_id,
            instagram_post_url=instagram_post_url,
            total_comments=result.get("total_comments", 0),
            positive_pct=agg.get("positive_pct", 0.0),
            neutral_pct=agg.get("neutral_pct", 0.0),
            negative_pct=agg.get("negative_pct", 0.0),
            avg_confidence=agg.get("avg_confidence", 0.0),
            full_result=result,
        )
        db.add(analysis)
        await db.commit()
    except Exception as e:
        logger.error("Failed to save analysis: %s", e)
        await db.rollback()


def _build_comparison(results):
    if not results:
        return {}
    most_positive = max(results, key=lambda r: r["aggregate"]["positive_pct"])
    most_negative = max(results, key=lambda r: r["aggregate"]["negative_pct"])
    counts = {k: sum(r["aggregate"][f"{k}_count"] for r in results) for k in ["positive", "neutral", "negative"]}
    overall = max(counts, key=counts.get)
    return {
        "most_positive_post": most_positive.get("label") or "Unlabeled",
        "most_negative_post": most_negative.get("label") or "Unlabeled",
        "overall_sentiment": overall,
        "total_comments_analyzed": sum(r["total_comments"] for r in results),
    }
