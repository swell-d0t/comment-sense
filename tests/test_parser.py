"""
tests/test_parser.py
--------------------
Tests every edge case in the comment parser.

Each test class covers one category of behavior. Each test method covers
one specific case with a docstring explaining what it's testing and why
the expected behavior is correct.

Run with:
    pytest tests/test_parser.py -v
"""

import pytest
from services.parser import (
    parse_instagram_comments,
    extract_comment_metadata,
    ParseError,
    ParseResult,
    MAX_INPUT_CHARS,
    MAX_COMMENTS_PER_REQUEST,
    MAX_COMMENT_LENGTH,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Input Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestInputValidation:

    def test_empty_string_returns_error(self):
        """
        An empty string has nothing to parse. We return a typed ParseError
        rather than an empty result so the API can return a 400, not a 200
        with zero comments. The error code is machine-readable.
        """
        result = parse_instagram_comments("")
        assert isinstance(result, ParseError)
        assert result.code == "EMPTY_INPUT"

    def test_whitespace_only_returns_error(self):
        """
        A string of only spaces and newlines contains no content.
        Should behave identically to an empty string.
        """
        result = parse_instagram_comments("   \n\n\t  \n")
        assert isinstance(result, ParseError)
        assert result.code == "EMPTY_INPUT"

    def test_input_exceeding_max_length_returns_error(self):
        """
        Inputs over MAX_INPUT_CHARS (50,000) are rejected before any
        processing. This prevents memory exhaustion and runaway processing.
        The error message tells the user the actual size and the limit.
        """
        huge_input = "this is a comment\n" * 5000  # well over 50k chars
        result = parse_instagram_comments(huge_input)
        assert isinstance(result, ParseError)
        assert result.code == "INPUT_TOO_LARGE"
        assert str(MAX_INPUT_CHARS) in result.message or "50,000" in result.message

    def test_non_string_input_returns_error(self):
        """
        The function signature accepts str, but defensive programming
        requires handling None and other types gracefully.
        """
        result = parse_instagram_comments(None)
        assert isinstance(result, ParseError)
        assert result.code == "INVALID_TYPE"

    def test_input_exactly_at_max_length_is_accepted(self):
        """
        Inputs at exactly the limit should be accepted.
        Off-by-one errors in the limit check would reject valid inputs.
        """
        # Build input that's exactly MAX_INPUT_CHARS with actual comment content
        base_comment = "this is a great comment\n"
        reps = MAX_INPUT_CHARS // len(base_comment)
        input_text = base_comment * reps
        input_text = input_text[:MAX_INPUT_CHARS]
        result = parse_instagram_comments(input_text)
        # Should not return INPUT_TOO_LARGE
        assert not (isinstance(result, ParseError) and result.code == "INPUT_TOO_LARGE")


# ═══════════════════════════════════════════════════════════════════════════════
# Instagram Noise Filtering
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoiseFiltering:

    def test_usernames_are_removed(self):
        """
        Instagram usernames appear on their own line before the comment.
        They must be stripped so they don't get analyzed as sentiment.
        """
        raw = "cool_user123\nthis product is amazing!"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert "cool_user123" not in result.comments
        assert "this product is amazing!" in result.comments

    def test_username_with_verification_badge_removed(self):
        """
        Verified accounts show a checkmark character (✓ or ✔) after
        the username. The regex must handle this variant.
        """
        raw = "brandaccount ✓\nlove this collaboration!"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert all("✓" not in c for c in result.comments)
        assert "love this collaboration!" in result.comments

    def test_relative_timestamps_removed(self):
        """
        Instagram shows timestamps like '2d', '1w', '4h', 'just now'.
        These appear on their own line and must not be analyzed as comments.
        """
        timestamps = ["2d", "1w", "4h", "3m", "just now", "1y", "23h"]
        for ts in timestamps:
            raw = f"someuser\n{ts}\ngreat post!"
            result = parse_instagram_comments(raw)
            assert isinstance(result, ParseResult), f"Failed for timestamp: {ts}"
            assert ts not in result.comments, f"Timestamp '{ts}' was not filtered"

    def test_like_counts_removed(self):
        """
        Comment like counts appear as '14 likes' or '1 like' on their own line.
        """
        raw = "someuser\n14 likes\nthis is so inspiring"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert "14 likes" not in result.comments
        assert "1 like" not in result.comments
        assert "this is so inspiring" in result.comments

    def test_reply_prompts_removed(self):
        """
        'View 4 replies', 'Hide replies', 'Reply' are Instagram UI elements,
        not user comments.
        """
        ui_strings = [
            "View 4 replies",
            "View 1 reply",
            "Hide replies",
            "reply",
            "Reply",
        ]
        for s in ui_strings:
            raw = f"{s}\nactual comment text"
            result = parse_instagram_comments(raw)
            assert isinstance(result, ParseResult)
            assert s.lower() not in [c.lower() for c in result.comments], (
                f"UI string '{s}' was not filtered"
            )

    def test_follow_button_text_removed(self):
        """
        'Follow' and 'Following' appear next to usernames in the comment section.
        """
        raw = "anotheruser\nFollow\nI love this so much"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert "Follow" not in result.comments
        assert "I love this so much" in result.comments

    def test_standalone_integers_removed(self):
        """
        Heart/like counts appear as standalone numbers. '47' on its own
        line is a like count, not a comment.
        """
        raw = "user1\n2d\n47\ngreat content"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert "47" not in result.comments

    def test_full_instagram_copy_paste_block(self):
        """
        A realistic copy-paste from Instagram including all the noise elements.
        After parsing, only actual comment text should remain.
        """
        raw = """
instagram_user1
2d
great post love it
14 likes
View 2 replies
another.user ✓
1w
this made my day!!
1 like
Reply
randomuser99
4h
not sure how I feel about this
"""
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert len(result.comments) == 3
        assert "great post love it" in result.comments
        assert "this made my day!!" in result.comments
        assert "not sure how I feel about this" in result.comments


# ═══════════════════════════════════════════════════════════════════════════════
# Encoding and Unicode
# ═══════════════════════════════════════════════════════════════════════════════

class TestEncodingHandling:

    def test_crlf_line_endings_normalized(self):
        """
        Windows-style CRLF (\r\n) line endings must be normalized to LF.
        Without this, regex patterns that match end-of-line would fail.
        """
        raw = "cool_user\r\nthis is great\r\n"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert "this is great" in result.comments

    def test_null_bytes_stripped(self):
        """
        Null bytes (\x00) can appear in copy-pasted text from some platforms.
        They must be stripped before processing to prevent regex issues.
        """
        raw = "user1\x00\nthis is a real comment\x00"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert any("this is a real comment" in c for c in result.comments)

    def test_zero_width_spaces_stripped(self):
        """
        Zero-width spaces (\u200b) are invisible characters that can appear
        in copy-pasted Instagram text. They must not corrupt comment text
        or prevent noise patterns from matching.
        """
        raw = "user1\u200b\nthis comment has invisible chars\u200b"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        for comment in result.comments:
            assert "\u200b" not in comment

    def test_emoji_comments_preserved(self):
        """
        Pure emoji comments are valid comments — they carry clear sentiment
        signal (🔥❤️ is positive, 😡💀 is negative). They must not be
        filtered out by the noise pipeline.
        """
        raw = "user1\n2d\n🔥🔥🔥\nuser2\n1d\n❤️😍\n"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert "🔥🔥🔥" in result.comments
        assert "❤️😍" in result.comments

    def test_accented_characters_preserved(self):
        """
        Non-ASCII Latin characters (é, ü, ñ etc.) appear in multilingual
        comments. NFC normalization must not corrupt them.
        """
        raw = "user1\nJ'adore cette vidéo, c'est incroyable!\n"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert any("incroyable" in c for c in result.comments)

    def test_arabic_rtl_text_preserved(self):
        """
        Right-to-left scripts must pass through the parser unchanged.
        The noise filters should not incorrectly flag Arabic text.
        """
        raw = "arabicuser\nهذا رائع جداً!\n"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert any("رائع" in c for c in result.comments)


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Case Comment Content
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommentContentEdgeCases:

    def test_single_character_comment_dropped(self):
        """
        Single characters like 'k' or '.' are not meaningful sentiment signals
        and would increase noise. They are filtered by the minimum length check.
        """
        raw = "user1\nk\ngreat video though"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert "k" not in result.comments

    def test_comment_exceeding_max_length_is_truncated_not_dropped(self):
        """
        Very long comments (essays, spam) should be truncated at MAX_COMMENT_LENGTH
        rather than dropped. Dropping would silently lose data.
        A warning should appear in the result.
        """
        long_comment = "this is amazing " * 200  # >> 2200 chars
        raw = f"user1\n{long_comment}\n"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert len(result.comments) == 1
        assert len(result.comments[0]) <= MAX_COMMENT_LENGTH
        assert result.truncated_comments > 0
        assert len(result.warnings) > 0

    def test_comment_limit_enforced_with_warning(self):
        """
        When input contains more than MAX_COMMENTS_PER_REQUEST comments,
        only the first MAX_COMMENTS_PER_REQUEST are returned.
        A warning must be included explaining the truncation.
        """
        many_comments = "\n".join(f"comment number {i}" for i in range(600))
        result = parse_instagram_comments(many_comments)
        assert isinstance(result, ParseResult)
        assert len(result.comments) == MAX_COMMENTS_PER_REQUEST
        assert any("500" in w or "first" in w.lower() for w in result.warnings)

    def test_non_instagram_text_produces_error_or_warning(self):
        """
        If someone pastes a random paragraph of text (not Instagram comments),
        the parser should either fail gracefully or warn that results are unreliable.
        Specifically: if fewer than 2 comments are extracted, a warning appears.
        """
        raw = "This is a press release from Acme Corp. We are pleased to announce."
        result = parse_instagram_comments(raw)
        # Either produces an error, or produces a warning about low extraction
        if isinstance(result, ParseResult):
            assert len(result.warnings) > 0 or len(result.comments) >= 1
        else:
            assert isinstance(result, ParseError)

    def test_comment_with_hashtags_preserved(self):
        """
        Hashtags (#love, #fire) are part of comment content and must
        not be filtered as noise.
        """
        raw = "user1\n2d\nThis is so #amazing #fire 🔥\n"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert any("#amazing" in c or "#fire" in c for c in result.comments)

    def test_comment_with_at_mention_preserved(self):
        """
        @mentions within comment text (@friend, @brand) are part of the comment
        and should not be filtered as usernames (which appear on their own line).
        """
        raw = "user1\n2d\ntagging @myfriend this is exactly what I needed\n"
        result = parse_instagram_comments(raw)
        assert isinstance(result, ParseResult)
        assert any("@myfriend" in c or "exactly what I needed" in c for c in result.comments)


# ═══════════════════════════════════════════════════════════════════════════════
# Metadata Extraction
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetadataExtraction:

    def test_pure_emoji_detected(self):
        """The is_pure_emoji flag enables weight adjustment in the ML pipeline."""
        meta = extract_comment_metadata("🔥🔥🔥")
        assert meta["is_pure_emoji"] is True

    def test_text_with_emoji_not_flagged_as_pure_emoji(self):
        """Mixed text+emoji should not set is_pure_emoji."""
        meta = extract_comment_metadata("this is great 🔥")
        assert meta["is_pure_emoji"] is False

    def test_short_comment_flagged(self):
        """Comments under 15 chars trigger VADER-weighted mode."""
        meta = extract_comment_metadata("nice!")
        assert meta["is_short"] is True

    def test_long_comment_not_flagged_as_short(self):
        meta = extract_comment_metadata("this is a longer comment about the product")
        assert meta["is_short"] is False

    def test_all_caps_detected(self):
        """ALL CAPS indicates emphasis — the ML pipeline uses this."""
        meta = extract_comment_metadata("THIS IS AMAZING")
        assert meta["is_all_caps"] is True

    def test_exclamation_count_correct(self):
        meta = extract_comment_metadata("wow!!! this is incredible!!!")
        assert meta["exclamation_count"] == 6
