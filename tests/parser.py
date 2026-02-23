"""
parser.py
---------
Responsible for one job: take raw Instagram copy-paste text and return
a clean list of comment strings with nothing else attached.

Edge cases handled:
  - Verified badge characters (✓ ✔ 󰀀)
  - Relative timestamps (2d, 1w, 4h, just now, yesterday, 1y)
  - Like counts (123 likes, 1 like)
  - Reply prompts (View 4 replies, Hide replies)
  - Follow/Suggested/Sponsored UI strings
  - Unicode control characters and null bytes
  - Inputs that are not Instagram comments at all
  - Non-UTF-8 byte sequences
  - Inputs that are entirely whitespace
  - Comments that are pure emoji (kept, not dropped)
  - Comments that are single characters (dropped — not meaningful)
  - Extremely long single lines (capped, not crashed)
  - Inputs exceeding the maximum allowed size (rejected early)
  - Windows-style line endings (CRLF normalized to LF)
  - Zero-width spaces and other invisible Unicode characters
"""

import re
import unicodedata
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Hard limits ──────────────────────────────────────────────────────────────
MAX_INPUT_CHARS = 50_000       # reject anything larger than this upfront
MAX_COMMENT_LENGTH = 2_200     # Instagram's own comment length limit is 2,200
MIN_COMMENT_LENGTH = 2         # single characters are not meaningful signal
MAX_COMMENTS_PER_REQUEST = 500 # downstream ML limit


# ── Compiled regex patterns (compiled once at import time, not per-call) ─────

# Relative timestamps Instagram uses
_RE_TIMESTAMP = re.compile(
    r'^\s*(\d+\s*[smhdwy]|just\s+now|yesterday|\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)\s*$',
    re.IGNORECASE
)

# Like counts: "123 likes", "1 like", standalone integers (the heart count)
_RE_LIKE_COUNT = re.compile(r'^\s*\d+\s+likes?\s*$', re.IGNORECASE)
_RE_STANDALONE_INT = re.compile(r'^\s*\d+\s*$')

# Reply UI strings
_RE_REPLY_PROMPT = re.compile(
    r'^\s*(view\s+\d+\s+repl(y|ies)|hide\s+repl(y|ies)|reply)\s*\.?\s*$',
    re.IGNORECASE
)

# Instagram UI noise strings (exact line matches)
_UI_STRINGS = frozenset([
    'follow', 'following', 'message', 'suggested', 'sponsored',
    'verified', 'see translation', 'translate', 'more', '...more',
    'load more comments', 'view all comments', 'liked by',
    'and', 'others',  # "liked by X and Y others"
])

# Username pattern: alphanumeric + dots + underscores, optionally with
# verification badge characters, optionally followed by a dot separator
# Instagram usernames: 1–30 chars, [a-z0-9._]
_RE_USERNAME_LINE = re.compile(
    r'''
    ^\s*
    [a-zA-Z0-9._]{1,30}   # the username itself
    \s*
    [✓✔󰀀]?               # optional verification badge
    \s*[·•]?\s*            # optional separator character
    $
    ''',
    re.VERBOSE
)

# Zero-width and invisible Unicode characters to strip inline
_RE_INVISIBLE = re.compile(
    r'[\u200b\u200c\u200d\u200e\u200f\u00ad\ufeff\u2028\u2029]'
)

# Control characters except tab and newline
_RE_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


# ── Public result types ───────────────────────────────────────────────────────

@dataclass
class ParseResult:
    comments: list[str]
    warnings: list[str] = field(default_factory=list)
    lines_processed: int = 0
    lines_dropped: int = 0
    truncated_comments: int = 0


@dataclass
class ParseError:
    code: str          # machine-readable code for the API to return
    message: str       # human-readable message for the UI


# ── Main entry point ──────────────────────────────────────────────────────────

def parse_instagram_comments(raw_text: str) -> ParseResult | ParseError:
    """
    Takes raw copy-pasted Instagram comment section text.
    Returns a ParseResult with clean comment strings, or a ParseError
    if the input is fundamentally unusable.

    This is the only function the rest of the application should call.
    """

    # ── Step 1: Input validation ──────────────────────────────────────────
    if not isinstance(raw_text, str):
        return ParseError(
            code="INVALID_TYPE",
            message="Input must be a string."
        )

    if len(raw_text) > MAX_INPUT_CHARS:
        return ParseError(
            code="INPUT_TOO_LARGE",
            message=(
                f"Input is {len(raw_text):,} characters. "
                f"Maximum allowed is {MAX_INPUT_CHARS:,}. "
                "Please split your comments into smaller batches."
            )
        )

    if not raw_text or not raw_text.strip():
        return ParseError(
            code="EMPTY_INPUT",
            message="No text was provided. Please paste your Instagram comments."
        )

    # ── Step 2: Normalize encoding and line endings ───────────────────────
    try:
        # Strip null bytes and control characters that can corrupt processing
        cleaned = _RE_CONTROL.sub('', raw_text)
        # Normalize CRLF and CR to LF
        cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
        # Strip zero-width and invisible characters
        cleaned = _RE_INVISIBLE.sub('', cleaned)
        # Normalize Unicode (NFC: canonical decomposition then canonical composition)
        # This handles accented characters that look identical but have different
        # byte representations — prevents duplicates and regex mismatches
        cleaned = unicodedata.normalize('NFC', cleaned)
    except Exception as e:
        logger.error("Encoding normalization failed: %s", e)
        return ParseError(
            code="ENCODING_ERROR",
            message="Could not process the text encoding. Try copying the comments again."
        )

    # ── Step 3: Split into lines and run filter passes ────────────────────
    lines = cleaned.split('\n')
    original_line_count = len(lines)
    warnings: list[str] = []
    truncated_count = 0

    filtered_lines = []
    for line in lines:
        stripped = line.strip()

        # Empty lines are structural separators, not content — skip silently
        if not stripped:
            continue

        # Cap line length before any pattern matching to prevent ReDoS
        if len(stripped) > MAX_COMMENT_LENGTH:
            stripped = stripped[:MAX_COMMENT_LENGTH]
            truncated_count += 1

        # Run noise filter passes in order of cheapest to most expensive
        if _is_noise_line(stripped):
            continue

        filtered_lines.append(stripped)

    # ── Step 4: Validate we actually extracted something ──────────────────
    if not filtered_lines:
        return ParseError(
            code="NO_COMMENTS_EXTRACTED",
            message=(
                "No comments could be extracted from the pasted text. "
                "This can happen if the text doesn't contain Instagram comments, "
                "or if all lines were identified as usernames/timestamps/UI elements. "
                "Try selecting just the comment section before copying."
            )
        )

    if len(filtered_lines) < 2:
        warnings.append(
            "Only 1 comment was extracted. If you expected more, check that you "
            "copied the full comment section including the comment text lines."
        )

    # ── Step 5: Enforce comment count limit ───────────────────────────────
    if len(filtered_lines) > MAX_COMMENTS_PER_REQUEST:
        warnings.append(
            f"Input contained {len(filtered_lines)} comments. "
            f"Only the first {MAX_COMMENTS_PER_REQUEST} will be analyzed. "
            "Use batch mode to analyze larger sets."
        )
        filtered_lines = filtered_lines[:MAX_COMMENTS_PER_REQUEST]

    if truncated_count > 0:
        warnings.append(
            f"{truncated_count} comment(s) were longer than {MAX_COMMENT_LENGTH} "
            "characters and were truncated. This is unusual and may indicate "
            "non-comment content was included."
        )

    lines_dropped = original_line_count - len(filtered_lines)

    return ParseResult(
        comments=filtered_lines,
        warnings=warnings,
        lines_processed=original_line_count,
        lines_dropped=lines_dropped,
        truncated_comments=truncated_count,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_noise_line(line: str) -> bool:
    """
    Returns True if this line should be dropped (it's Instagram UI noise,
    not a user comment). Runs a sequence of pattern checks from cheapest
    to most expensive.
    """

    # Exact match against known UI strings (O(1) set lookup)
    if line.lower() in _UI_STRINGS:
        return True

    # Line is too short to be a meaningful comment
    if len(line) < MIN_COMMENT_LENGTH:
        return True

    # Timestamp line
    if _RE_TIMESTAMP.match(line):
        return True

    # Like count line
    if _RE_LIKE_COUNT.match(line):
        return True

    # Standalone integer (heart count shown separately)
    if _RE_STANDALONE_INT.match(line):
        return True

    # Reply UI prompts
    if _RE_REPLY_PROMPT.match(line):
        return True

    # Username-only line
    if _RE_USERNAME_LINE.match(line):
        return True

    return False


def _is_pure_emoji(text: str) -> bool:
    """
    Returns True if the string consists entirely of emoji characters
    and whitespace. Pure emoji comments are KEPT (not noise-filtered)
    because they carry clear sentiment signal, but this flag is used
    downstream to adjust model weighting.
    """
    for char in text.strip():
        if char.isspace():
            continue
        # Unicode category 'So' = other symbol, which covers most emoji
        # Category 'Sk' = modifier symbol (skin tone modifiers etc.)
        cat = unicodedata.category(char)
        if cat not in ('So', 'Sk', 'Mn', 'Cs'):
            # Check explicitly for emoji ranges that aren't caught by category
            cp = ord(char)
            is_emoji_range = (
                0x1F600 <= cp <= 0x1F64F or  # emoticons
                0x1F300 <= cp <= 0x1F5FF or  # misc symbols
                0x1F680 <= cp <= 0x1F6FF or  # transport
                0x1F1E0 <= cp <= 0x1F1FF or  # flags
                0x2600  <= cp <= 0x26FF  or  # misc symbols
                0x2700  <= cp <= 0x27BF  or  # dingbats
                0xFE00  <= cp <= 0xFE0F       # variation selectors
            )
            if not is_emoji_range:
                return False
    return True


def extract_comment_metadata(comment: str) -> dict:
    """
    Returns metadata about a comment that the ML pipeline uses to
    adjust model behavior. Called per-comment after parsing.
    """
    return {
        "is_pure_emoji": _is_pure_emoji(comment),
        "char_length": len(comment),
        "is_short": len(comment) < 15,
        "has_emoji": any(
            unicodedata.category(c) in ('So', 'Sk') for c in comment
        ),
        "is_all_caps": (
            comment.isupper() and len(comment) > 3
        ),  # "LOVE THIS" is intentional emphasis
        "exclamation_count": comment.count('!'),
    }
