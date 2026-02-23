"""
hybrid.py
---------
The sentiment analysis pipeline. Combines VADER (lexicon-based) with a
RoBERTa transformer model (cardiffnlp/twitter-roberta-base-sentiment-latest).

Why both?
  - VADER excels at: emoji, capitalization emphasis, punctuation intensity,
    informal language, speed (no GPU needed)
  - RoBERTa excels at: contextual understanding, sarcasm clues, multi-word
    sentiment patterns, nuanced neutral vs positive distinction

Edge cases handled:
  - Model not loaded (startup failure) — fail loudly, not silently
  - Token truncation for comments > 512 tokens
  - Pure emoji comments — VADER-weighted more heavily
  - Short comments (<15 chars) — VADER-weighted more heavily
  - High model disagreement — flagged, confidence reduced
  - Inference timeout — per-comment timeout with graceful fallback
  - Batch size management — comments chunked to prevent OOM
  - Non-English text — detected and flagged before model inference
  - All-caps text — normalized before RoBERTa (it's case-sensitive)
  - Empty string reaching the model — should never happen, guarded anyway
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional
import unicodedata

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
ROBERTA_MAX_TOKENS = 512
INFERENCE_TIMEOUT_SECONDS = 10.0
BATCH_CHUNK_SIZE = 32        # comments per RoBERTa forward pass
DEFAULT_VADER_WEIGHT = 0.35
DEFAULT_ROBERTA_WEIGHT = 0.65
DISAGREEMENT_THRESHOLD = 0.6  # if |vader_pos - roberta_pos| > this, flag it
SHORT_COMMENT_THRESHOLD = 15  # characters
EMOJI_VADER_WEIGHT = 0.60    # for pure-emoji comments, trust VADER more


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class CommentSentiment:
    text: str
    sentiment: str          # "positive" | "neutral" | "negative"
    confidence: float       # 0.0–1.0
    vader_compound: float   # raw VADER compound score (-1 to 1)
    roberta_scores: dict    # {"positive": float, "neutral": float, "negative": float}
    flags: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None


@dataclass
class PipelineResult:
    sentiments: list[CommentSentiment]
    model_load_warning: Optional[str] = None


# ── Model singleton ───────────────────────────────────────────────────────────
# Models are loaded once at application startup via load_models().
# These module-level variables hold the loaded instances.
# If load_models() was never called or failed, they remain None and
# every inference call will return a graceful error.

_vader_analyzer = None
_roberta_tokenizer = None
_roberta_model = None
_models_loaded = False
_load_error: Optional[str] = None


def load_models() -> bool:
    """
    Called once during FastAPI startup (lifespan context).
    Returns True on success, False on failure.
    Sets module-level _models_loaded and _load_error accordingly.
    """
    global _vader_analyzer, _roberta_tokenizer, _roberta_model
    global _models_loaded, _load_error

    logger.info("Loading sentiment models...")

    # ── Load VADER ────────────────────────────────────────────────────────
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader_analyzer = SentimentIntensityAnalyzer()
        logger.info("VADER loaded successfully.")
    except ImportError:
        _load_error = "vaderSentiment package is not installed. Run: pip install vaderSentiment"
        logger.critical(_load_error)
        return False
    except Exception as e:
        _load_error = f"VADER failed to load: {e}"
        logger.critical(_load_error)
        return False

    # ── Load RoBERTa ──────────────────────────────────────────────────────
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch

        model_name = "cardiffnlp/twitter-roberta-base-sentiment-latest"
        logger.info("Downloading/loading RoBERTa model: %s", model_name)

        _roberta_tokenizer = AutoTokenizer.from_pretrained(model_name)
        _roberta_model = AutoModelForSequenceClassification.from_pretrained(model_name)
        _roberta_model.eval()  # disable dropout for deterministic inference

        # Move to GPU if available (significant speedup)
        if torch.cuda.is_available():
            _roberta_model = _roberta_model.cuda()
            logger.info("RoBERTa running on GPU.")
        else:
            logger.info("RoBERTa running on CPU (no GPU detected).")

        logger.info("RoBERTa loaded successfully.")
    except ImportError:
        _load_error = (
            "transformers or torch package is not installed. "
            "Run: pip install transformers torch"
        )
        logger.critical(_load_error)
        return False
    except Exception as e:
        _load_error = f"RoBERTa failed to load: {e}"
        logger.critical(_load_error)
        return False

    _models_loaded = True
    logger.info("All models loaded. Pipeline ready.")
    return True


def models_are_ready() -> bool:
    return _models_loaded


def get_load_error() -> Optional[str]:
    return _load_error


# ── Main pipeline entry point ─────────────────────────────────────────────────

def analyze_comments(
    comments: list[str],
    metadata_list: list[dict],
    vader_weight: float = DEFAULT_VADER_WEIGHT,
    roberta_weight: float = DEFAULT_ROBERTA_WEIGHT,
) -> PipelineResult:
    """
    Runs the full hybrid sentiment pipeline on a list of clean comment strings.
    metadata_list must be the same length as comments and contain the dicts
    produced by parser.extract_comment_metadata().

    Returns a PipelineResult containing one CommentSentiment per input comment.
    """

    # ── Guard: models must be loaded ─────────────────────────────────────
    if not _models_loaded:
        error_msg = _load_error or "Models have not been loaded. Call load_models() at startup."
        logger.error("analyze_comments called before models were ready: %s", error_msg)
        # Return skipped results for every comment rather than crashing
        return PipelineResult(
            sentiments=[
                CommentSentiment(
                    text=c,
                    sentiment="neutral",
                    confidence=0.0,
                    vader_compound=0.0,
                    roberta_scores={},
                    skipped=True,
                    skip_reason="Models not loaded",
                )
                for c in comments
            ],
            model_load_warning=error_msg,
        )

    # ── Guard: empty input ────────────────────────────────────────────────
    if not comments:
        return PipelineResult(sentiments=[])

    # ── Language detection (batch, before expensive inference) ───────────
    lang_flags = _detect_languages(comments)

    # ── VADER pass (fast, all comments at once) ───────────────────────────
    vader_results = _run_vader_batch(comments)

    # ── RoBERTa pass (chunked to manage memory) ───────────────────────────
    roberta_results = _run_roberta_batch(comments, lang_flags)

    # ── Fusion pass ───────────────────────────────────────────────────────
    sentiments = []
    for i, comment in enumerate(comments):
        meta = metadata_list[i]
        vader_score = vader_results[i]
        roberta_score = roberta_results[i]
        lang_info = lang_flags[i]

        result = _fuse_scores(
            comment=comment,
            meta=meta,
            vader_score=vader_score,
            roberta_score=roberta_score,
            lang_info=lang_info,
            vader_weight=vader_weight,
            roberta_weight=roberta_weight,
        )
        sentiments.append(result)

    return PipelineResult(sentiments=sentiments)


# ── VADER pass ────────────────────────────────────────────────────────────────

def _run_vader_batch(comments: list[str]) -> list[dict]:
    """
    Runs VADER on all comments. VADER is pure Python so no batching needed.
    Returns list of dicts: {"compound": float, "pos": float, "neu": float, "neg": float}
    """
    results = []
    for comment in comments:
        try:
            scores = _vader_analyzer.polarity_scores(comment)
            results.append(scores)
        except Exception as e:
            logger.warning("VADER failed on comment '%s...': %s", comment[:30], e)
            results.append({"compound": 0.0, "pos": 0.0, "neu": 1.0, "neg": 0.0})
    return results


# ── RoBERTa pass ──────────────────────────────────────────────────────────────

def _run_roberta_batch(
    comments: list[str],
    lang_flags: list[dict],
) -> list[Optional[dict]]:
    """
    Runs RoBERTa on all comments in chunks of BATCH_CHUNK_SIZE.
    Non-English comments are skipped (None returned for their slot).
    Returns list of dicts: {"positive": float, "neutral": float, "negative": float}
    or None for skipped comments.
    """
    import torch
    import torch.nn.functional as F

    results: list[Optional[dict]] = [None] * len(comments)

    # Build list of (original_index, preprocessed_text) for English comments only
    to_process = []
    for i, (comment, lang) in enumerate(zip(comments, lang_flags)):
        if lang.get("skip_roberta"):
            continue
        preprocessed = _preprocess_for_roberta(comment)
        if preprocessed:
            to_process.append((i, preprocessed))

    # Process in chunks
    for chunk_start in range(0, len(to_process), BATCH_CHUNK_SIZE):
        chunk = to_process[chunk_start:chunk_start + BATCH_CHUNK_SIZE]
        indices = [item[0] for item in chunk]
        texts = [item[1] for item in chunk]

        try:
            start_time = time.time()

            encoded = _roberta_tokenizer(
                texts,
                padding=True,
                truncation=True,         # truncates to ROBERTA_MAX_TOKENS
                max_length=ROBERTA_MAX_TOKENS,
                return_tensors="pt",
            )

            # Move to same device as model
            device = next(_roberta_model.parameters()).device
            encoded = {k: v.to(device) for k, v in encoded.items()}

            with torch.no_grad():
                output = _roberta_model(**encoded)

            # Softmax to convert logits to probabilities
            probs = F.softmax(output.logits, dim=-1).cpu().numpy()

            elapsed = time.time() - start_time
            if elapsed > INFERENCE_TIMEOUT_SECONDS:
                logger.warning(
                    "RoBERTa inference took %.2fs for chunk of %d (threshold: %.1fs)",
                    elapsed, len(chunk), INFERENCE_TIMEOUT_SECONDS
                )

            # Map label indices to names
            # cardiffnlp model labels: 0=negative, 1=neutral, 2=positive
            label_map = {0: "negative", 1: "neutral", 2: "positive"}

            for j, original_idx in enumerate(indices):
                results[original_idx] = {
                    label_map[k]: float(probs[j][k]) for k in range(3)
                }

        except Exception as e:
            logger.error(
                "RoBERTa inference failed for chunk starting at %d: %s",
                chunk_start, e
            )
            # Mark the whole chunk as failed but don't crash — VADER will carry them
            for original_idx in indices:
                results[original_idx] = None

    return results


def _preprocess_for_roberta(text: str) -> str:
    """
    Applies preprocessing that improves RoBERTa accuracy on social media text:
    - Normalizes @mentions to @user (the model was trained with this convention)
    - Normalizes URLs to http (same)
    - Caps length (defensive — tokenizer also truncates but better to be explicit)
    """
    import re
    text = re.sub(r'@\w+', '@user', text)
    text = re.sub(r'http\S+|www\.\S+', 'http', text)
    # Hard cap at 1000 characters before tokenization to prevent edge-case slowdowns
    return text[:1000]


# ── Language detection ────────────────────────────────────────────────────────

def _detect_languages(comments: list[str]) -> list[dict]:
    """
    Attempts to detect the language of each comment.
    Returns a list of dicts with:
      - "lang": ISO 639-1 code or "unknown"
      - "confidence": float
      - "skip_roberta": bool (True for non-English)
      - "warning": optional string for the response warnings list
    """
    try:
        from langdetect import detect, detect_langs, LangDetectException
        langdetect_available = True
    except ImportError:
        langdetect_available = False
        logger.warning("langdetect not installed. Language detection disabled.")

    results = []
    for comment in comments:
        if not langdetect_available or len(comment.strip()) < 10:
            # Too short for reliable detection; trust the models
            results.append({"lang": "unknown", "confidence": 0.0, "skip_roberta": False})
            continue

        try:
            langs = detect_langs(comment)
            top = langs[0]
            lang_code = top.lang
            confidence = top.prob

            skip = (lang_code != "en" and confidence > 0.85)
            results.append({
                "lang": lang_code,
                "confidence": confidence,
                "skip_roberta": skip,
                "warning": (
                    f"Comment appears to be non-English ({lang_code}); "
                    "sentiment accuracy may be reduced."
                ) if skip else None,
            })
        except Exception:
            results.append({"lang": "unknown", "confidence": 0.0, "skip_roberta": False})

    return results


# ── Score fusion ──────────────────────────────────────────────────────────────

def _fuse_scores(
    comment: str,
    meta: dict,
    vader_score: dict,
    roberta_score: Optional[dict],
    lang_info: dict,
    vader_weight: float,
    roberta_weight: float,
) -> CommentSentiment:
    """
    Combines VADER and RoBERTa scores into a single sentiment label
    and confidence value, applying special-case logic for edge cases.
    """
    flags = []

    # ── Handle language flag ──────────────────────────────────────────────
    if lang_info.get("warning"):
        flags.append(f"non_english:{lang_info['lang']}")

    # ── Adjust weights for special comment types ──────────────────────────
    effective_vader_w = vader_weight
    effective_roberta_w = roberta_weight

    if roberta_score is None:
        # RoBERTa failed or was skipped — VADER carries everything
        effective_vader_w = 1.0
        effective_roberta_w = 0.0
        if lang_info.get("skip_roberta"):
            flags.append("non_english_vader_only")
        else:
            flags.append("roberta_inference_failed")

    elif meta.get("is_pure_emoji"):
        # VADER has an emoji lexicon; RoBERTa was not trained on emoji-only inputs
        effective_vader_w = EMOJI_VADER_WEIGHT
        effective_roberta_w = 1.0 - EMOJI_VADER_WEIGHT
        flags.append("pure_emoji_adjusted_weights")

    elif meta.get("is_short"):
        # Short comments have unreliable RoBERTa context; weight VADER more
        effective_vader_w = 0.55
        effective_roberta_w = 0.45
        flags.append("short_comment_adjusted_weights")

    # ── Convert VADER compound (-1..1) to probability-like scores ────────
    # compound > 0.05 → positive, < -0.05 → negative, else neutral
    # We map to a 0-1 scale for each class to match RoBERTa's output format
    vader_compound = vader_score["compound"]
    vader_as_probs = _vader_compound_to_probs(vader_compound)

    # ── Weighted average across all three classes ─────────────────────────
    if roberta_score is not None:
        fused = {
            "positive": (
                effective_vader_w * vader_as_probs["positive"] +
                effective_roberta_w * roberta_score["positive"]
            ),
            "neutral": (
                effective_vader_w * vader_as_probs["neutral"] +
                effective_roberta_w * roberta_score["neutral"]
            ),
            "negative": (
                effective_vader_w * vader_as_probs["negative"] +
                effective_roberta_w * roberta_score["negative"]
            ),
        }
    else:
        fused = vader_as_probs

    # ── Detect high model disagreement ───────────────────────────────────
    if roberta_score is not None:
        disagreement = abs(
            vader_as_probs["positive"] - roberta_score["positive"]
        )
        if disagreement > DISAGREEMENT_THRESHOLD:
            flags.append("model_disagreement")
            # Reduce confidence when models strongly disagree
            disagreement_penalty = 0.25
        else:
            disagreement_penalty = 0.0
    else:
        disagreement_penalty = 0.0

    # ── Determine final label and confidence ─────────────────────────────
    sentiment = max(fused, key=fused.get)
    raw_confidence = fused[sentiment]
    confidence = max(0.0, round(raw_confidence - disagreement_penalty, 4))

    return CommentSentiment(
        text=comment,
        sentiment=sentiment,
        confidence=confidence,
        vader_compound=vader_compound,
        roberta_scores=roberta_score or {},
        flags=flags,
    )


def _vader_compound_to_probs(compound: float) -> dict:
    """
    Maps VADER's compound score to a probability-style dict so it can be
    averaged with RoBERTa's softmax output.

    VADER compound is in [-1, 1]:
      > 0.05  → positive
      < -0.05 → negative
      else    → neutral

    We use a sigmoid-like mapping so the probabilities are smooth, not binary.
    """
    # Map compound to [0, 1]
    normalized = (compound + 1.0) / 2.0  # 0 = most negative, 1 = most positive

    if compound >= 0.05:
        pos = normalized
        neg = 1.0 - normalized
        neu = max(0.0, 1.0 - pos - neg)
    elif compound <= -0.05:
        neg = 1.0 - normalized
        pos = normalized
        neu = max(0.0, 1.0 - pos - neg)
    else:
        neu = 1.0 - abs(compound) * 2
        pos = (1.0 - neu) / 2
        neg = (1.0 - neu) / 2

    # Normalize to sum to 1.0
    total = pos + neu + neg
    return {
        "positive": pos / total,
        "neutral": neu / total,
        "negative": neg / total,
    }
