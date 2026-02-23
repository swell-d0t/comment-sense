"""
tests/test_token_store.py
-------------------------
Tests all OAuth and token handling edge cases.

These tests mock Redis, the database, and the Meta API so they
can run without any external dependencies.

Run with:
    pytest tests/test_token_store.py -v
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta, timezone
from services.token_store import (
    encrypt_token,
    decrypt_token,
    store_oauth_state,
    verify_and_consume_oauth_state,
    generate_oauth_state,
    should_refresh_token,
    refresh_long_lived_token,
    get_valid_token,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Token Encryption / Decryption
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenEncryption:

    def setup_method(self):
        """Set a valid test encryption key before each test."""
        from cryptography.fernet import Fernet
        self.test_key = Fernet.generate_key().decode()

    def test_encrypt_and_decrypt_roundtrip(self):
        """
        A token that is encrypted then decrypted should return the
        original plaintext. The fundamental correctness test.
        """
        with patch.dict("os.environ", {"ENCRYPTION_KEY": self.test_key}):
            original = "EAABsbCS4iHABO2..."
            encrypted = encrypt_token(original)
            decrypted = decrypt_token(encrypted)
            assert decrypted == original

    def test_encrypted_token_does_not_equal_plaintext(self):
        """
        The encrypted value must not be the same as the plaintext.
        If this fails, encryption is not working.
        """
        with patch.dict("os.environ", {"ENCRYPTION_KEY": self.test_key}):
            original = "EAABsbCS4iHABO2..."
            encrypted = encrypt_token(original)
            assert encrypted != original

    def test_missing_encryption_key_raises_runtime_error(self):
        """
        If ENCRYPTION_KEY is not set, the app should fail loudly at the
        point of use, not silently store plaintext tokens.
        """
        with patch.dict("os.environ", {}, clear=True):
            # Remove the key if it's set
            import os
            os.environ.pop("ENCRYPTION_KEY", None)
            with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
                encrypt_token("some_token")

    def test_malformed_encryption_key_raises_runtime_error(self):
        """
        An invalid key format (not a valid Fernet key) should raise a
        clear error, not a cryptic one from the cryptography library.
        """
        with patch.dict("os.environ", {"ENCRYPTION_KEY": "not_a_valid_fernet_key"}):
            with pytest.raises(RuntimeError):
                encrypt_token("some_token")

    def test_decrypt_corrupted_token_returns_none(self):
        """
        If the encrypted token is corrupted (database corruption, wrong key),
        decrypt_token must return None rather than raising an exception.
        The caller treats None as a revoked token and triggers re-auth.
        """
        with patch.dict("os.environ", {"ENCRYPTION_KEY": self.test_key}):
            result = decrypt_token("this_is_not_a_valid_encrypted_token")
            assert result is None

    def test_decrypt_token_encrypted_with_different_key_returns_none(self):
        """
        If the key in the environment changes (key rotation), tokens
        encrypted with the old key cannot be decrypted. This must return
        None gracefully, not crash.
        """
        from cryptography.fernet import Fernet
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        # Encrypt with old key
        with patch.dict("os.environ", {"ENCRYPTION_KEY": old_key}):
            encrypted = encrypt_token("my_access_token")

        # Try to decrypt with new key
        with patch.dict("os.environ", {"ENCRYPTION_KEY": new_key}):
            result = decrypt_token(encrypted)
            assert result is None

    def test_different_tokens_produce_different_ciphertexts(self):
        """Each token must produce a unique encrypted value."""
        with patch.dict("os.environ", {"ENCRYPTION_KEY": self.test_key}):
            enc1 = encrypt_token("token_one")
            enc2 = encrypt_token("token_two")
            assert enc1 != enc2

    def test_same_token_encrypted_twice_produces_different_ciphertexts(self):
        """
        Fernet uses a random IV, so encrypting the same plaintext twice
        should produce different ciphertexts. This prevents an attacker
        from detecting if two users have the same token.
        """
        with patch.dict("os.environ", {"ENCRYPTION_KEY": self.test_key}):
            enc1 = encrypt_token("same_token")
            enc2 = encrypt_token("same_token")
            assert enc1 != enc2


# ═══════════════════════════════════════════════════════════════════════════════
# OAuth State Management
# ═══════════════════════════════════════════════════════════════════════════════

class TestOAuthStateManagement:

    def _make_redis_mock(self):
        """Creates a mock Redis client with the methods we use."""
        mock = MagicMock()
        mock.ping.return_value = True
        mock.setex.return_value = True
        mock.getdel.return_value = "1"  # state exists by default
        return mock

    def test_generate_state_stores_in_redis(self):
        """
        generate_oauth_state() should generate a random string and
        store it in Redis. Returns the state string on success.
        """
        redis_mock = self._make_redis_mock()
        with patch("services.token_store._get_redis", return_value=redis_mock):
            state = generate_oauth_state()
            assert state is not None
            assert len(state) >= 32  # must be long enough to prevent guessing
            redis_mock.setex.assert_called_once()

    def test_generate_state_returns_none_when_redis_unavailable(self):
        """
        If Redis is unavailable, we cannot safely do OAuth.
        generate_oauth_state must return None so the caller can
        abort the flow rather than proceed without CSRF protection.
        """
        with patch("services.token_store._get_redis", return_value=None):
            state = generate_oauth_state()
            assert state is None

    def test_verify_valid_state_returns_true(self):
        """A valid state that exists in Redis should verify successfully."""
        redis_mock = self._make_redis_mock()
        redis_mock.getdel.return_value = "1"
        with patch("services.token_store._get_redis", return_value=redis_mock):
            result = verify_and_consume_oauth_state("a" * 32)
            assert result is True

    def test_verify_expired_state_returns_false(self):
        """
        A state that has expired or was never stored should return False.
        getdel returns None for missing keys.
        """
        redis_mock = self._make_redis_mock()
        redis_mock.getdel.return_value = None  # key not found
        with patch("services.token_store._get_redis", return_value=redis_mock):
            result = verify_and_consume_oauth_state("a" * 32)
            assert result is False

    def test_verify_state_is_consumed_on_first_use(self):
        """
        The state must be deleted from Redis when verified.
        A second verification attempt with the same state must fail.
        This prevents replay attacks where an attacker captures the
        redirect URL and reuses it.
        """
        redis_mock = self._make_redis_mock()
        # First call returns the state, second returns None (already deleted)
        redis_mock.getdel.side_effect = ["1", None]
        with patch("services.token_store._get_redis", return_value=redis_mock):
            first = verify_and_consume_oauth_state("a" * 32)
            second = verify_and_consume_oauth_state("a" * 32)
            assert first is True
            assert second is False

    def test_verify_short_state_rejected_immediately(self):
        """
        A state that's too short cannot be cryptographically secure.
        Reject it without even checking Redis.
        """
        with patch("services.token_store._get_redis") as mock_redis:
            result = verify_and_consume_oauth_state("short")
            assert result is False
            mock_redis.assert_not_called()

    def test_verify_empty_state_rejected(self):
        """Empty state string must be rejected."""
        with patch("services.token_store._get_redis") as mock_redis:
            result = verify_and_consume_oauth_state("")
            assert result is False
            mock_redis.assert_not_called()

    def test_verify_returns_false_when_redis_unavailable(self):
        """
        If Redis is down during the callback, we cannot verify the state.
        We must reject the OAuth flow entirely rather than proceeding
        without CSRF validation.
        """
        with patch("services.token_store._get_redis", return_value=None):
            result = verify_and_consume_oauth_state("a" * 32)
            assert result is False

    def test_each_state_is_unique(self):
        """Two generated states must not be the same."""
        redis_mock = self._make_redis_mock()
        with patch("services.token_store._get_redis", return_value=redis_mock):
            state1 = generate_oauth_state()
            state2 = generate_oauth_state()
            assert state1 != state2


# ═══════════════════════════════════════════════════════════════════════════════
# Token Refresh Logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenRefreshLogic:

    def test_should_refresh_when_expiring_within_threshold(self):
        """Token expiring in 3 days (< 7 day threshold) should trigger refresh."""
        expiry = datetime.now(timezone.utc) + timedelta(days=3)
        assert should_refresh_token(expiry) is True

    def test_should_not_refresh_when_expiry_far_away(self):
        """Token expiring in 30 days should not trigger refresh."""
        expiry = datetime.now(timezone.utc) + timedelta(days=30)
        assert should_refresh_token(expiry) is False

    def test_should_refresh_already_expired_token(self):
        """An already-expired token should trigger refresh (which will then fail with 401)."""
        expiry = datetime.now(timezone.utc) - timedelta(days=1)
        assert should_refresh_token(expiry) is True

    def test_should_refresh_exactly_at_threshold(self):
        """Token expiring exactly at the 7-day threshold should trigger refresh."""
        expiry = datetime.now(timezone.utc) + timedelta(days=7, seconds=-1)
        assert should_refresh_token(expiry) is True

    @pytest.mark.asyncio
    async def test_refresh_returns_new_token_on_success(self):
        """
        Successful refresh should return the new token and update the database.
        """
        redis_mock = MagicMock()
        redis_mock.set.return_value = True
        redis_mock.delete.return_value = True

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_long_lived_token",
            "expires_in": 5184000  # 60 days
        }

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("services.token_store._get_redis", return_value=redis_mock):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                    return_value=mock_response
                )
                with patch("services.token_store._update_token_in_db", new_callable=AsyncMock):
                    with patch.dict("os.environ", {
                        "META_APP_ID": "test_id",
                        "META_APP_SECRET": "test_secret",
                        "ENCRYPTION_KEY": __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
                    }):
                        result = await refresh_long_lived_token(
                            current_token="old_token",
                            user_id=1,
                            db=mock_db,
                        )

        assert result == "new_long_lived_token"

    @pytest.mark.asyncio
    async def test_refresh_returns_none_on_401_and_clears_token(self):
        """
        A 401 from Meta means the user revoked access.
        The token should be deleted from the database and None returned.
        The caller will redirect the user to reconnect.
        """
        redis_mock = MagicMock()
        redis_mock.set.return_value = True

        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_db = AsyncMock()

        with patch("services.token_store._get_redis", return_value=redis_mock):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                    return_value=mock_response
                )
                with patch("services.token_store._handle_revoked_token", new_callable=AsyncMock) as mock_revoke:
                    with patch.dict("os.environ", {
                        "META_APP_ID": "test_id",
                        "META_APP_SECRET": "test_secret",
                    }):
                        result = await refresh_long_lived_token(
                            current_token="revoked_token",
                            user_id=1,
                            db=mock_db,
                        )

        assert result is None
        mock_revoke.assert_called_once_with(1, mock_db)

    @pytest.mark.asyncio
    async def test_refresh_returns_none_on_network_timeout(self):
        """
        If the Meta API times out, refresh should return None gracefully.
        The existing token remains valid until actual expiry.
        """
        import httpx
        redis_mock = MagicMock()
        redis_mock.set.return_value = True
        mock_db = AsyncMock()

        with patch("services.token_store._get_redis", return_value=redis_mock):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                    side_effect=httpx.TimeoutException("timed out")
                )
                with patch.dict("os.environ", {
                    "META_APP_ID": "test_id",
                    "META_APP_SECRET": "test_secret",
                }):
                    result = await refresh_long_lived_token(
                        current_token="old_token",
                        user_id=1,
                        db=mock_db,
                    )

        assert result is None

    @pytest.mark.asyncio
    async def test_concurrent_refresh_uses_redis_lock(self):
        """
        When two simultaneous requests try to refresh the same user's token,
        the Redis lock should prevent double-refresh. The second attempt
        should return the existing token immediately without making an API call.
        """
        redis_mock = MagicMock()
        # First call acquires lock, second call fails to acquire
        redis_mock.set.side_effect = [True, None]  # nx=True: first succeeds, second fails

        mock_db = AsyncMock()
        mock_http_get = AsyncMock()

        with patch("services.token_store._get_redis", return_value=redis_mock):
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get = mock_http_get
                with patch.dict("os.environ", {
                    "META_APP_ID": "test_id",
                    "META_APP_SECRET": "test_secret",
                }):
                    result = await refresh_long_lived_token(
                        current_token="existing_token",
                        user_id=1,
                        db=mock_db,
                    )

        # Second call should return existing token without calling the API
        assert result == "existing_token"
        mock_http_get.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# get_valid_token (end-to-end token retrieval)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetValidToken:

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_user(self):
        """A user ID that doesn't exist in the database should return None."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_valid_token(user_id=99999, db=mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_user_without_token(self):
        """A user who hasn't connected Instagram has no token."""
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.instagram_token = None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_valid_token(user_id=1, db=mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_decryption_failure_triggers_revoke(self):
        """
        If the stored token cannot be decrypted, the token record should
        be deleted and None returned. This handles database corruption and
        key rotation scenarios.
        """
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.instagram_token = "corrupted_encrypted_token"
        mock_user.instagram_token_expires = datetime.now(timezone.utc) + timedelta(days=30)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("services.token_store.decrypt_token", return_value=None):
            with patch("services.token_store._handle_revoked_token", new_callable=AsyncMock) as mock_revoke:
                result = await get_valid_token(user_id=1, db=mock_db)

        assert result is None
        mock_revoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_near_expiry_token_triggers_refresh(self):
        """
        A token expiring within the refresh threshold should be automatically
        refreshed. The caller receives the new token, not the old one.
        """
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.instagram_token = "encrypted_old_token"
        # Token expires in 3 days (within 7-day threshold)
        mock_user.instagram_token_expires = datetime.now(timezone.utc) + timedelta(days=3)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("services.token_store.decrypt_token", return_value="old_plaintext_token"):
            with patch("services.token_store.refresh_long_lived_token", new_callable=AsyncMock) as mock_refresh:
                mock_refresh.return_value = "new_plaintext_token"
                result = await get_valid_token(user_id=1, db=mock_db)

        assert result == "new_plaintext_token"
        mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_unexpired_token_returned_without_refresh(self):
        """
        A valid token far from expiry should be returned as-is
        without triggering a refresh API call.
        """
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.instagram_token = "encrypted_valid_token"
        mock_user.instagram_token_expires = datetime.now(timezone.utc) + timedelta(days=45)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("services.token_store.decrypt_token", return_value="valid_plaintext_token"):
            with patch("services.token_store.refresh_long_lived_token", new_callable=AsyncMock) as mock_refresh:
                result = await get_valid_token(user_id=1, db=mock_db)

        assert result == "valid_plaintext_token"
        mock_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_database_error_returns_none_gracefully(self):
        """
        If the database throws an exception, get_valid_token should
        return None rather than propagating the exception to the caller.
        """
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB connection lost"))

        result = await get_valid_token(user_id=1, db=mock_db)
        assert result is None
