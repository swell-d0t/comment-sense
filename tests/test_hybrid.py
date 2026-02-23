"""
tests/test_hybrid.py
--------------------
Tests the hybrid ML sentiment pipeline edge cases.

Because the actual RoBERTa model is large (~500MB) and requires GPU/CPU
inference, these tests use two strategies:
  1. Unit tests that mock the model and test pure logic (score fusion,
     weight adjustment, disagreement detection)
  2. Integration tests marked @pytest.mark.integration that require
     the real model to be loaded — skipped in CI by default

Run unit tests only:
    pytest tests/test_hybrid.py -v -m "not integration"

Run all including integration:
    pytest tests/test_hybrid.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
from services.hybrid import (
    _vader_compound_to_probs,
    _fuse_scores,
    _is_pure_emoji_adjusted,
    analyze_comments,
    models_are_ready,
    DISAGREEMENT_THRESHOLD,
    CommentSentiment,
)
from services.parser import extract_comment_metadata


# ═══════════════════════════════════════════════════════════════════════════════
# VADER Compound Conversion
# ═══════════════════════════════════════════════════════════════════════════════

class TestVaderCompoundConversion:

    def test_strongly_positive_compound(self):
        """
        VADER compound of 0.8 (strongly positive) should produce
        a probability distribution where 'positive' is the dominant class.
        """
        probs = _vader_compound_to_probs(0.8)
        assert probs["positive"] > probs["neutral"]
        assert probs["positive"] > probs["negative"]

    def test_strongly_negative_compound(self):
        """
        VADER compound of -0.8 should make 'negative' the dominant class.
        """
        probs = _vader_compound_to_probs(-0.8)
        assert probs["negative"] > probs["neutral"]
        assert probs["negative"] > probs["positive"]

    def test_neutral_compound(self):
        """
        VADER compound of 0.0 (neutral) should make 'neutral' dominant.
        """
        probs = _vader_compound_to_probs(0.0)
        assert probs["neutral"] > probs["positive"]
        assert probs["neutral"] > probs["negative"]

    def test_probabilities_sum_to_one(self):
        """
        The three output probabilities must always sum to 1.0.
        If they don't, the weighted average with RoBERTa will be wrong.
        """
        for compound in [-1.0, -0.5, -0.1, 0.0, 0.1, 0.5, 1.0]:
            probs = _vader_compound_to_probs(compound)
            total = sum(probs.values())
            assert abs(total - 1.0) < 0.001, (
                f"Probabilities don't sum to 1.0 for compound={compound}: {probs}"
            )

    def test_all_probabilities_non_negative(self):
        """No probability value should ever be negative."""
        for compound in [-1.0, -0.5, 0.0, 0.5, 1.0]:
            probs = _vader_compound_to_probs(compound)
            for label, val in probs.items():
                assert val >= 0.0, (
                    f"Negative probability for '{label}' at compound={compound}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# Score Fusion Logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreFusion:

    def _make_meta(self, **kwargs):
        """Helper to create a metadata dict with defaults."""
        defaults = {
            "is_pure_emoji": False,
            "is_short": False,
            "has_emoji": False,
            "is_all_caps": False,
            "exclamation_count": 0,
            "char_length": 50,
        }
        defaults.update(kwargs)
        return defaults

    def _make_lang(self, **kwargs):
        defaults = {"lang": "en", "confidence": 0.99, "skip_roberta": False}
        defaults.update(kwargs)
        return defaults

    def test_both_models_agree_positive_high_confidence(self):
        """
        When VADER and RoBERTa both strongly agree the comment is positive,
        the fused result should be positive with high confidence.
        No disagreement flag should be set.
        """
        result = _fuse_scores(
            comment="this is absolutely amazing I love it",
            meta=self._make_meta(),
            vader_score={"compound": 0.85, "pos": 0.8, "neu": 0.2, "neg": 0.0},
            roberta_score={"positive": 0.91, "neutral": 0.07, "negative": 0.02},
            lang_info=self._make_lang(),
            vader_weight=0.35,
            roberta_weight=0.65,
        )
        assert result.sentiment == "positive"
        assert result.confidence > 0.7
        assert "model_disagreement" not in result.flags

    def test_model_disagreement_flagged(self):
        """
        When VADER says strongly positive but RoBERTa says strongly negative
        (a sarcasm case), the result should be flagged as model_disagreement
        and confidence should be reduced.
        """
        result = _fuse_scores(
            comment="oh great another delay, just what I needed",
            meta=self._make_meta(),
            # VADER sees "great" and scores it positive
            vader_score={"compound": 0.6, "pos": 0.5, "neu": 0.3, "neg": 0.2},
            # RoBERTa detects sarcasm and scores it negative
            roberta_score={"positive": 0.08, "neutral": 0.12, "negative": 0.80},
            lang_info=self._make_lang(),
            vader_weight=0.35,
            roberta_weight=0.65,
        )
        assert "model_disagreement" in result.flags
        # Confidence should be penalized
        assert result.confidence < 0.65

    def test_roberta_failure_falls_back_to_vader(self):
        """
        If RoBERTa returns None (inference error), VADER carries the full
        weight. The result should still have a valid sentiment label.
        A flag should be set indicating RoBERTa failed.
        """
        result = _fuse_scores(
            comment="I really love this product",
            meta=self._make_meta(),
            vader_score={"compound": 0.72, "pos": 0.6, "neu": 0.4, "neg": 0.0},
            roberta_score=None,  # RoBERTa failed
            lang_info=self._make_lang(),
            vader_weight=0.35,
            roberta_weight=0.65,
        )
        assert result.sentiment in ("positive", "neutral", "negative")
        assert "roberta_inference_failed" in result.flags

    def test_pure_emoji_adjusts_weights(self):
        """
        For pure-emoji comments, VADER should be weighted more heavily
        because it has an emoji lexicon and RoBERTa was not trained on
        emoji-only inputs. The flag should reflect this adjustment.
        """
        result = _fuse_scores(
            comment="🔥🔥🔥",
            meta=self._make_meta(is_pure_emoji=True),
            vader_score={"compound": 0.7, "pos": 0.6, "neu": 0.4, "neg": 0.0},
            roberta_score={"positive": 0.4, "neutral": 0.4, "negative": 0.2},
            lang_info=self._make_lang(),
            vader_weight=0.35,
            roberta_weight=0.65,
        )
        assert "pure_emoji_adjusted_weights" in result.flags

    def test_short_comment_adjusts_weights(self):
        """
        Short comments (<15 chars) lack context for RoBERTa.
        The flag should indicate weight adjustment occurred.
        """
        result = _fuse_scores(
            comment="lol ok",
            meta=self._make_meta(is_short=True, char_length=6),
            vader_score={"compound": 0.1, "pos": 0.2, "neu": 0.7, "neg": 0.1},
            roberta_score={"positive": 0.3, "neutral": 0.5, "negative": 0.2},
            lang_info=self._make_lang(),
            vader_weight=0.35,
            roberta_weight=0.65,
        )
        assert "short_comment_adjusted_weights" in result.flags

    def test_non_english_comment_flagged(self):
        """
        Non-English comments (detected with high confidence) should be
        flagged in the result so the UI can warn the user.
        """
        result = _fuse_scores(
            comment="Das ist wirklich toll!",
            meta=self._make_meta(),
            vader_score={"compound": 0.5, "pos": 0.5, "neu": 0.5, "neg": 0.0},
            roberta_score=None,
            lang_info={"lang": "de", "confidence": 0.97, "skip_roberta": True},
            vader_weight=0.35,
            roberta_weight=0.65,
        )
        assert any("non_english" in f for f in result.flags)

    def test_confidence_is_between_zero_and_one(self):
        """
        Confidence must always be in [0, 1]. The disagreement penalty
        could theoretically push it below zero — this must be clamped.
        """
        result = _fuse_scores(
            comment="test",
            meta=self._make_meta(is_short=True),
            vader_score={"compound": 0.1, "pos": 0.1, "neu": 0.8, "neg": 0.1},
            roberta_score={"positive": 0.05, "neutral": 0.1, "negative": 0.85},
            lang_info=self._make_lang(),
            vader_weight=0.35,
            roberta_weight=0.65,
        )
        assert 0.0 <= result.confidence <= 1.0

    def test_sentiment_label_is_always_valid(self):
        """
        The sentiment label must always be one of the three valid values,
        never None or an unexpected string.
        """
        valid_labels = {"positive", "neutral", "negative"}
        for compound in [-1.0, -0.3, 0.0, 0.3, 1.0]:
            result = _fuse_scores(
                comment="test comment",
                meta=self._make_meta(),
                vader_score={"compound": compound, "pos": 0.3, "neu": 0.4, "neg": 0.3},
                roberta_score={"positive": 0.3, "neutral": 0.4, "negative": 0.3},
                lang_info=self._make_lang(),
                vader_weight=0.35,
                roberta_weight=0.65,
            )
            assert result.sentiment in valid_labels


# ═══════════════════════════════════════════════════════════════════════════════
# Full Pipeline (Mocked Models)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullPipelineMocked:

    def test_models_not_loaded_returns_skipped_results(self):
        """
        If analyze_comments is called before load_models(), every comment
        should come back as skipped=True with a clear skip_reason.
        The pipeline must not crash.
        """
        with patch("services.hybrid._models_loaded", False):
            with patch("services.hybrid._load_error", "Models not loaded in test"):
                result = analyze_comments(
                    comments=["this is a great product"],
                    metadata_list=[extract_comment_metadata("this is a great product")],
                )
        assert len(result.sentiments) == 1
        assert result.sentiments[0].skipped is True
        assert result.model_load_warning is not None

    def test_empty_comment_list_returns_empty_result(self):
        """An empty input list should return an empty result, not crash."""
        with patch("services.hybrid._models_loaded", True):
            result = analyze_comments(comments=[], metadata_list=[])
        assert result.sentiments == []

    @patch("services.hybrid._run_roberta_batch")
    @patch("services.hybrid._run_vader_batch")
    @patch("services.hybrid._detect_languages")
    def test_roberta_chunk_failure_doesnt_crash_pipeline(
        self, mock_lang, mock_vader, mock_roberta
    ):
        """
        If RoBERTa raises an exception for a batch chunk, the pipeline
        should not crash. Comments from that chunk should be marked with
        the roberta_inference_failed flag and fall back to VADER.
        """
        comments = ["great product", "love this", "not bad"]
        metas = [extract_comment_metadata(c) for c in comments]

        mock_lang.return_value = [
            {"lang": "en", "confidence": 0.99, "skip_roberta": False}
        ] * 3
        mock_vader.return_value = [
            {"compound": 0.7, "pos": 0.6, "neu": 0.4, "neg": 0.0},
            {"compound": 0.8, "pos": 0.7, "neu": 0.3, "neg": 0.0},
            {"compound": 0.2, "pos": 0.3, "neu": 0.6, "neg": 0.1},
        ]
        # RoBERTa returns None for all (simulates complete failure)
        mock_roberta.return_value = [None, None, None]

        with patch("services.hybrid._models_loaded", True):
            result = analyze_comments(
                comments=comments,
                metadata_list=metas,
            )

        assert len(result.sentiments) == 3
        # All should have roberta_inference_failed flag
        for sentiment in result.sentiments:
            assert "roberta_inference_failed" in sentiment.flags
            assert sentiment.sentiment in ("positive", "neutral", "negative")


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Tests (require real models)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestRealModelInference:
    """
    These tests require load_models() to have been called.
    Skip with: pytest -m "not integration"
    """

    def test_obviously_positive_comment(self):
        """A clearly positive comment should be labeled positive."""
        from services.hybrid import load_models
        if not models_are_ready():
            load_models()

        result = analyze_comments(
            comments=["This is absolutely incredible, I love everything about it!!!"],
            metadata_list=[extract_comment_metadata("This is absolutely incredible, I love everything about it!!!")],
        )
        assert result.sentiments[0].sentiment == "positive"

    def test_obviously_negative_comment(self):
        """A clearly negative comment should be labeled negative."""
        from services.hybrid import load_models
        if not models_are_ready():
            load_models()

        result = analyze_comments(
            comments=["This is terrible, absolute garbage, completely disappointed"],
            metadata_list=[extract_comment_metadata("This is terrible, absolute garbage, completely disappointed")],
        )
        assert result.sentiments[0].sentiment == "negative"

    def test_positive_emoji_comment(self):
        """🔥❤️ should produce a positive result via VADER's emoji lexicon."""
        from services.hybrid import load_models
        if not models_are_ready():
            load_models()

        result = analyze_comments(
            comments=["🔥❤️😍🙌"],
            metadata_list=[extract_comment_metadata("🔥❤️😍🙌")],
        )
        assert result.sentiments[0].sentiment == "positive"
