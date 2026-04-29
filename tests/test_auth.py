"""Tests for TonnTokenVerifier (introspection-based token verification)."""

import time

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from tonn_mcp.auth import TonnTokenVerifier


@pytest.fixture
def verifier():
    return TonnTokenVerifier(
        introspection_endpoint="http://localhost:5000/introspect"
    )


def _make_introspect_response(active=True, **kwargs):
    """Build a mock httpx.Response for introspection."""
    data = {"active": active}
    if active:
        data.update({
            "client_id": kwargs.get("client_id", "tonn_abc123"),
            "scope": kwargs.get("scope", "read:account process:audio"),
            "exp": kwargs.get("exp", int(time.time()) + 3600),
            "iat": kwargs.get("iat", int(time.time())),
            "token_type": "Bearer",
            "sub": kwargs.get("sub", "user_123"),
            "api_key": kwargs.get("api_key", "pk_test_key"),
            "credits_remaining": kwargs.get("credits_remaining", 1000),
        })

    response = httpx.Response(
        status_code=kwargs.get("status_code", 200),
        json=data,
        request=httpx.Request("POST", "http://localhost:5000/introspect"),
    )
    return response


@pytest.mark.asyncio
class TestVerifyToken:
    async def test_active_token_returns_access_token(self, verifier):
        mock_response = _make_introspect_response(active=True)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("test_token_abc")

        assert result is not None
        assert result.token == "test_token_abc"
        assert result.client_id == "tonn_abc123"
        assert "read:account" in result.scopes
        assert "process:audio" in result.scopes

    async def test_inactive_token_returns_none(self, verifier):
        mock_response = _make_introspect_response(active=False)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("inactive_token")

        assert result is None

    async def test_cache_hit_avoids_http_call(self, verifier):
        mock_response = _make_introspect_response(active=True)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.auth.httpx.AsyncClient", return_value=mock_client):
            first = await verifier.verify_token("cached_token")
            second = await verifier.verify_token("cached_token")

        assert first is not None
        assert second is not None
        assert first.token == second.token
        # Only one HTTP call should have been made
        assert mock_client.post.call_count == 1

    async def test_http_error_returns_none(self, verifier):
        mock_response = httpx.Response(
            status_code=500,
            json={"error": "internal"},
            request=httpx.Request("POST", "http://localhost:5000/introspect"),
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("error_token")

        assert result is None

    async def test_timeout_returns_none(self, verifier):
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verifier.verify_token("timeout_token")

        assert result is None

    async def test_unsafe_scheme_rejected(self):
        v = TonnTokenVerifier(
            introspection_endpoint="http://evil.example.com/introspect"
        )
        result = await v.verify_token("any_token")
        assert result is None


class TestGetUserContext:
    def test_returns_cached_data(self, verifier):
        from tonn_mcp.auth import CachedIntrospection
        from mcp.server.auth.provider import AccessToken

        at = AccessToken(
            token="ctx_token",
            client_id="tonn_abc",
            scopes=["read:account"],
        )
        verifier._cache["ctx_token"] = CachedIntrospection(
            access_token=at,
            api_key="pk_test",
            credits_remaining=500,
            user_id="user_1",
            expires_at=time.time() + 60,
        )

        ctx = verifier.get_user_context("ctx_token")
        assert ctx is not None
        assert ctx.api_key == "pk_test"
        assert ctx.credits_remaining == 500

    def test_returns_none_when_not_cached(self, verifier):
        ctx = verifier.get_user_context("uncached_token")
        assert ctx is None

    def test_returns_none_when_expired(self, verifier):
        from tonn_mcp.auth import CachedIntrospection
        from mcp.server.auth.provider import AccessToken

        at = AccessToken(
            token="expired_ctx",
            client_id="tonn_abc",
            scopes=[],
        )
        verifier._cache["expired_ctx"] = CachedIntrospection(
            access_token=at,
            api_key="pk_test",
            credits_remaining=100,
            user_id="user_1",
            expires_at=time.time() - 10,
        )

        ctx = verifier.get_user_context("expired_ctx")
        assert ctx is None
