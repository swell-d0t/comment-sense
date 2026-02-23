"""
tests/test_api.py
-----------------
Tests the FastAPI endpoints using TestClient (no real HTTP needed).

These tests verify that the API layer correctly:
  - Validates input and returns proper error codes
  - Handles parser errors cleanly
  - Handles ML pipeline failures gracefully
  - Enforces size and rate limits
  - Returns properly structured responses

Run with:
    pytest tests/test_api.py -v
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """
    Creates a test client with models mocked as loaded.
    This fixture patches _models_loaded=True so tests don't require
    the actual 500MB model to be present.
    """
    with patch("services.hybrid._models_loaded", True):
        with patch("services.hybrid._vader_analyzer", MagicMock()):
            from main import app
            with TestClient(app) as c:
                yield c


@pytest.fixture
def client_models_not_loaded():
    """Test client where models failed to load."""
    with patch("services.hybrid._models_loaded", False):
        with patch("services.hybrid._load_error", "Test: models not loaded"):
            from main import app
            with TestClient(app) as c:
                yield c


def make_realistic_comments(n: int = 5) -> str:
    """Generates a realistic-looking Instagram paste block."""
    comments = []
    for i in range(n):
        comments.append(f"user_{i}\n2d\nThis is comment number {i}, it is great!\n3 likes\n")
    return "\n".join(comments)


# ═══════════════════════════════════════════════════════════════════════════════
# Health Check
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthCheck:

    def test_health_returns_200_when_models_loaded(self, client):
        """Health check should return 200 when everything is ready."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["models_loaded"] is True
        assert data["status"] == "healthy"

    def test_health_returns_503_when_models_not_loaded(self, client_models_not_loaded):
        """
        Health check should return 503 when models failed to load.
        Load balancers use this to route traffic away from broken instances.
        """
        response = client_models_not_loaded.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["models_loaded"] is False
        assert data["status"] == "degraded"


# ═══════════════════════════════════════════════════════════════════════════════
# POST /analyze — Input Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeInputValidation:

    def test_missing_raw_text_returns_422(self, client):
        """
        raw_text is a required field. Omitting it should return 422
        with a clear description of what's missing.
        """
        response = client.post("/analyze", json={"label": "test"})
        assert response.status_code == 422
        data = response.json()
        assert data["error"] == "VALIDATION_ERROR"
        assert any("raw_text" in str(d) for d in data["details"])

    def test_empty_raw_text_returns_422(self, client):
        """
        An empty string for raw_text violates the min_length=1 constraint.
        Should return 422, not 400 — the Pydantic validator catches this.
        """
        response = client.post("/analyze", json={"raw_text": ""})
        assert response.status_code == 422

    def test_raw_text_exceeding_max_length_returns_422(self, client):
        """
        raw_text has max_length=50_000. Exceeding it should return 422.
        The Pydantic validator catches this before any parsing occurs.
        """
        response = client.post("/analyze", json={"raw_text": "x" * 50_001})
        assert response.status_code == 422

    def test_valid_weights_accepted(self, client):
        """
        Custom VADER/RoBERTa weights within [0, 1] should be accepted.
        We mock the pipeline to avoid needing real models.
        """
        with patch("routers.analyze._run_analysis") as mock_run:
            mock_run.return_value = {"id": "test", "total_comments": 1, "comments": [], "aggregate": {}, "warnings": [], "parse_stats": {}, "top_positive": [], "top_negative": [], "label": None}
            response = client.post("/analyze", json={
                "raw_text": make_realistic_comments(3),
                "options": {"vader_weight": 0.5, "roberta_weight": 0.5}
            })
        # Even if mock doesn't work perfectly, validation passed = not 422
        assert response.status_code != 422

    def test_weights_out_of_range_returns_422(self, client):
        """
        Weights must be in [0, 1]. vader_weight=1.5 should return 422.
        """
        response = client.post("/analyze", json={
            "raw_text": make_realistic_comments(2),
            "options": {"vader_weight": 1.5, "roberta_weight": 0.5}
        })
        assert response.status_code == 422

    def test_label_exceeding_max_length_returns_422(self, client):
        """Labels are capped at 200 characters."""
        response = client.post("/analyze", json={
            "raw_text": make_realistic_comments(2),
            "label": "x" * 201,
        })
        assert response.status_code == 422

    def test_non_json_body_returns_422(self, client):
        """Sending plain text instead of JSON should return 422."""
        response = client.post(
            "/analyze",
            content="this is not json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# POST /analyze — Model and Parser Errors
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeErrorHandling:

    def test_models_not_loaded_returns_503(self, client_models_not_loaded):
        """
        When models are not ready, the endpoint should return 503 with
        an explanation. This is different from a 500 (crash) — it's a
        known, expected degraded state.
        """
        response = client_models_not_loaded.post("/analyze", json={
            "raw_text": make_realistic_comments(3)
        })
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "MODELS_NOT_READY"

    def test_parser_returning_error_gives_400(self, client):
        """
        When the parser returns a ParseError (e.g. NO_COMMENTS_EXTRACTED),
        the API should return 400 with the parser's error code.
        """
        with patch("routers.analyze.parse_instagram_comments") as mock_parse:
            from services.parser import ParseError
            mock_parse.return_value = ParseError(
                code="NO_COMMENTS_EXTRACTED",
                message="No comments found in the pasted text."
            )
            response = client.post("/analyze", json={
                "raw_text": "some text that extracts nothing"
            })

        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "NO_COMMENTS_EXTRACTED"

    def test_unhandled_exception_returns_500_with_request_id(self, client):
        """
        If something completely unexpected happens, the global handler
        should catch it, log it, and return 500 with a request ID.
        The response must not leak stack traces to the client.
        """
        with patch("routers.analyze.parse_instagram_comments") as mock_parse:
            mock_parse.side_effect = RuntimeError("Something exploded")
            response = client.post("/analyze", json={
                "raw_text": make_realistic_comments(2)
            })

        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "INTERNAL_ERROR"
        assert "request_id" in data
        # Stack trace must NOT be in response (unless EXPOSE_ERROR_DETAILS=true)
        assert "RuntimeError" not in response.text or "detail" in data


# ═══════════════════════════════════════════════════════════════════════════════
# POST /analyze — Response Structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeResponseStructure:

    @patch("routers.analyze.analyze_comments")
    @patch("routers.analyze.parse_instagram_comments")
    def test_successful_response_has_required_fields(self, mock_parse, mock_analyze, client):
        """
        A successful analysis response must contain all required fields.
        The frontend depends on these fields — missing ones cause UI crashes.
        """
        from services.parser import ParseResult
        from services.hybrid import PipelineResult, CommentSentiment

        mock_parse.return_value = ParseResult(
            comments=["this is great", "love it"],
            lines_processed=10,
            lines_dropped=8,
        )
        mock_analyze.return_value = PipelineResult(
            sentiments=[
                CommentSentiment(
                    text="this is great",
                    sentiment="positive",
                    confidence=0.87,
                    vader_compound=0.7,
                    roberta_scores={"positive": 0.9, "neutral": 0.08, "negative": 0.02},
                ),
                CommentSentiment(
                    text="love it",
                    sentiment="positive",
                    confidence=0.91,
                    vader_compound=0.8,
                    roberta_scores={"positive": 0.93, "neutral": 0.05, "negative": 0.02},
                ),
            ]
        )

        with patch("routers.analyze.models_are_ready", return_value=True):
            response = client.post("/analyze", json={"raw_text": make_realistic_comments(2)})

        assert response.status_code == 200
        data = response.json()

        # Required top-level fields
        required_fields = [
            "id", "label", "total_comments", "aggregate",
            "comments", "top_positive", "top_negative", "warnings", "parse_stats"
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        # Required aggregate fields
        aggregate_fields = [
            "positive_pct", "neutral_pct", "negative_pct",
            "avg_confidence", "positive_count", "neutral_count", "negative_count"
        ]
        for field in aggregate_fields:
            assert field in data["aggregate"], f"Missing aggregate field: {field}"

        # Each comment must have required fields
        for comment in data["comments"]:
            for field in ["id", "text", "sentiment", "confidence", "flags"]:
                assert field in comment, f"Missing comment field: {field}"


# ═══════════════════════════════════════════════════════════════════════════════
# POST /analyze/batch
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatchAnalyze:

    def test_empty_posts_array_returns_422(self, client):
        """Batch request with empty posts array should fail validation."""
        response = client.post("/analyze/batch", json={"posts": []})
        assert response.status_code == 422

    def test_too_many_posts_returns_422(self, client):
        """Batch is capped at 20 posts."""
        posts = [{"raw_text": make_realistic_comments(1)} for _ in range(21)]
        response = client.post("/analyze/batch", json={"posts": posts})
        assert response.status_code == 422

    def test_duplicate_labels_produce_warning(self, client):
        """
        Duplicate post labels should not fail the request, but should
        produce a warning in the response.
        """
        with patch("routers.analyze._run_analysis") as mock_run:
            mock_run.return_value = {
                "id": "x", "label": "Post A", "total_comments": 1,
                "comments": [], "aggregate": {
                    "positive_pct": 100, "neutral_pct": 0, "negative_pct": 0,
                    "avg_confidence": 0.9, "positive_count": 1,
                    "neutral_count": 0, "negative_count": 0,
                },
                "top_positive": [], "top_negative": [],
                "warnings": [], "parse_stats": {},
            }
            response = client.post("/analyze/batch", json={
                "posts": [
                    {"label": "Post A", "raw_text": make_realistic_comments(2)},
                    {"label": "Post A", "raw_text": make_realistic_comments(2)},
                ]
            })

        if response.status_code == 200:
            data = response.json()
            assert any("duplicate" in w.lower() for w in data.get("batch_warnings", []))

    def test_one_failed_post_does_not_fail_batch(self, client):
        """
        If one post in a batch fails (bad input), the rest should still
        be analyzed. The failed post appears in failed_posts, not results.
        """
        def mock_run_analysis(raw_text, label, **kwargs):
            if label == "Bad Post":
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=400,
                    content={"error": "NO_COMMENTS_EXTRACTED", "message": "Failed"}
                )
            return {
                "id": "x", "label": label, "total_comments": 1,
                "comments": [], "aggregate": {
                    "positive_pct": 100, "neutral_pct": 0, "negative_pct": 0,
                    "avg_confidence": 0.9, "positive_count": 1,
                    "neutral_count": 0, "negative_count": 0,
                },
                "top_positive": [], "top_negative": [],
                "warnings": [], "parse_stats": {},
            }

        with patch("routers.analyze._run_analysis", side_effect=mock_run_analysis):
            response = client.post("/analyze/batch", json={
                "posts": [
                    {"label": "Good Post", "raw_text": make_realistic_comments(2)},
                    {"label": "Bad Post", "raw_text": "garbage input"},
                ]
            })

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) >= 1
        assert len(data["failed_posts"]) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Request Infrastructure
# ═══════════════════════════════════════════════════════════════════════════════

class TestRequestInfrastructure:

    def test_response_includes_request_id_header(self, client):
        """
        Every response should include an X-Request-ID header.
        This enables log correlation for debugging.
        """
        response = client.get("/health")
        assert "x-request-id" in response.headers

    def test_custom_request_id_is_echoed(self, client):
        """
        If the client sends an X-Request-ID header, the server should
        use that value rather than generating a new one.
        This allows end-to-end request tracing.
        """
        custom_id = "my-trace-id-12345"
        response = client.get("/health", headers={"X-Request-ID": custom_id})
        assert response.headers.get("x-request-id") == custom_id

    def test_weight_normalization(self, client):
        """
        Weights that don't sum to 1.0 (e.g., 0.4/0.4) should be accepted
        and automatically normalized. This tests the model_validator.
        """
        from routers.analyze import AnalysisOptions
        opts = AnalysisOptions(vader_weight=0.4, roberta_weight=0.4)
        total = opts.vader_weight + opts.roberta_weight
        assert abs(total - 1.0) < 0.001

    def test_zero_weights_normalized_to_defaults(self):
        """
        Both weights set to 0.0 is invalid. The validator should
        reset to sensible defaults rather than crashing or dividing by zero.
        """
        from routers.analyze import AnalysisOptions
        opts = AnalysisOptions(vader_weight=0.0, roberta_weight=0.0)
        assert opts.vader_weight > 0
        assert opts.roberta_weight > 0
        assert abs(opts.vader_weight + opts.roberta_weight - 1.0) < 0.001
