"""
routers/analyze.py
------------------
Handles POST /analyze and POST /analyze/batch.

Edge cases handled:
  - Models not loaded — returns 503 with explanation
  - Parser returns an error — returns 400 with the parser's message
  - Empty comment list after parsing — returns 400
  - Batch with duplicate labels — warns but proceeds
  - Batch with zero valid posts — returns 400
  - Weight parameters out of range — Pydantic validation catches this
  - Weight parameters that don't sum to 1.0 — normalized automatically
  - Individual post failures in batch — don't fail the whole batch
"""

import logging
from typing import Optional
import uuid

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.parser import parse_instagram_comments, extract_comment_metadata, ParseError
from services.hybrid import analyze_comments, models_are_ready, get_load_error

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AnalysisOptions(BaseModel):
    vader_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    roberta_weight: float = Field(default=0.65, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def normalize_weights(self) -> "AnalysisOptions":
        """
        If weights don't sum to 1.0, normalize them rather than rejecting.
        This is friendlier UX — a user sending 0.4/0.4 shouldn't get an error.
        """
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
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)


class BatchPost(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)
    raw_text: str = Field(..., min_length=1, max_length=50_000)


class BatchAnalyzeRequest(BaseModel):
    posts: list[BatchPost] = Field(..., min_length=1, max_length=20)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)


# ── POST /analyze ─────────────────────────────────────────────────────────────

@router.post("")
@limiter.limit("10/minute")
async def analyze_single(request: Request, body: AnalyzeRequest):
    """Analyze comments from a single Instagram post."""

    # Guard: models must be loaded
    if not models_are_ready():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "MODELS_NOT_READY",
                "message": (
                    "The sentiment analysis models are not available. "
                    "This may be a temporary startup issue. Please try again in a moment."
                ),
                "detail": get_load_error(),
            },
        )

    result = _run_analysis(
        raw_text=body.raw_text,
        label=body.label,
        vader_weight=body.options.vader_weight,
        roberta_weight=body.options.roberta_weight,
    )

    if isinstance(result, JSONResponse):
        return result

    return result


# ── POST /analyze/batch ───────────────────────────────────────────────────────

@router.post("/batch")
@limiter.limit("5/minute")
async def analyze_batch(request: Request, body: BatchAnalyzeRequest):
    """Analyze comments from multiple Instagram posts."""

    if not models_are_ready():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "MODELS_NOT_READY",
                "message": "Models are not available. Please try again shortly.",
            },
        )

    # Warn about duplicate labels (proceed anyway)
    labels = [p.label for p in body.posts if p.label]
    duplicate_labels = [l for l in labels if labels.count(l) > 1]
    batch_warnings = []
    if duplicate_labels:
        batch_warnings.append(
            f"Duplicate post labels detected: {list(set(duplicate_labels))}. "
            "Consider using unique labels for clearer comparison."
        )

    results = []
    failed_posts = []

    for post in body.posts:
        try:
            result = _run_analysis(
                raw_text=post.raw_text,
                label=post.label,
                vader_weight=body.options.vader_weight,
                roberta_weight=body.options.roberta_weight,
            )
            # If this post produced a hard error, record it but continue
            if isinstance(result, JSONResponse):
                failed_posts.append({
                    "label": post.label or "Unlabeled",
                    "error": result.body.decode(),
                })
            else:
                results.append(result)
        except Exception as e:
            logger.error("Unexpected error analyzing post '%s': %s", post.label, e)
            failed_posts.append({
                "label": post.label or "Unlabeled",
                "error": "Unexpected error during analysis.",
            })

    if not results:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "ALL_POSTS_FAILED",
                "message": "No posts could be successfully analyzed.",
                "failed_posts": failed_posts,
            },
        )

    comparison = _build_comparison(results)

    return {
        "results": results,
        "comparison": comparison,
        "batch_warnings": batch_warnings,
        "failed_posts": failed_posts,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _run_analysis(
    raw_text: str,
    label: Optional[str],
    vader_weight: float,
    roberta_weight: float,
) -> dict | JSONResponse:
    """
    Core analysis logic shared between single and batch endpoints.
    Returns a result dict on success, or a JSONResponse on failure.
    """

    # Parse
    parse_result = parse_instagram_comments(raw_text)

    if isinstance(parse_result, ParseError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": parse_result.code,
                "message": parse_result.message,
            },
        )

    comments = parse_result.comments
    metadata_list = [extract_comment_metadata(c) for c in comments]

    # Run ML pipeline
    pipeline_result = analyze_comments(
        comments=comments,
        metadata_list=metadata_list,
        vader_weight=vader_weight,
        roberta_weight=roberta_weight,
    )

    # Build aggregate stats
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

    # Sort to find top positive/negative
    sorted_by_pos = sorted(
        [s for s in sentiments if s.sentiment == "positive"],
        key=lambda x: x.confidence,
        reverse=True,
    )
    sorted_by_neg = sorted(
        [s for s in sentiments if s.sentiment == "negative"],
        key=lambda x: x.confidence,
        reverse=True,
    )

    warnings = list(parse_result.warnings)
    if pipeline_result.model_load_warning:
        warnings.append(pipeline_result.model_load_warning)
    if non_english_count > 0:
        warnings.append(
            f"{non_english_count} comment(s) may be non-English. "
            "Sentiment accuracy for these may be reduced."
        )

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
        "top_positive": [s.text for s in sorted_by_pos[:3]],
        "top_negative": [s.text for s in sorted_by_neg[:3]],
        "warnings": warnings,
    }


def _build_comparison(results: list[dict]) -> dict:
    """Builds the cross-post comparison summary for batch results."""
    if not results:
        return {}

    most_positive = max(results, key=lambda r: r["aggregate"]["positive_pct"])
    most_negative = max(results, key=lambda r: r["aggregate"]["negative_pct"])

    total_comments = sum(r["total_comments"] for r in results)
    total_positive = sum(r["aggregate"]["positive_count"] for r in results)
    total_neutral = sum(r["aggregate"]["neutral_count"] for r in results)
    total_negative = sum(r["aggregate"]["negative_count"] for r in results)

    overall = max(
        ["positive", "neutral", "negative"],
        key=lambda s: {"positive": total_positive, "neutral": total_neutral, "negative": total_negative}[s]
    )

    return {
        "most_positive_post": most_positive.get("label") or "Unlabeled",
        "most_negative_post": most_negative.get("label") or "Unlabeled",
        "overall_sentiment": overall,
        "total_comments_analyzed": total_comments,
    }
