"""
Token verification via introspection against the Tonn Portal Authorization Server.

Follows the SDK's TokenVerifier protocol (simple-auth/token_verifier.py pattern).
Adds a short-lived cache to avoid hitting the introspection endpoint on every request.
"""

import logging
import time
from dataclasses import dataclass

import httpx

from mcp.server.auth.provider import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)

CACHE_TTL = 60  # seconds


@dataclass
class CachedIntrospection:
    access_token: AccessToken
    api_key: str | None
    credits_remaining: int | None
    user_id: str | None
    expires_at: float


class TonnTokenVerifier(TokenVerifier):
    """Verifies OAuth tokens by calling the Tonn Portal's /introspect endpoint."""

    def __init__(self, introspection_endpoint: str):
        self.introspection_endpoint = introspection_endpoint
        self._cache: dict[str, CachedIntrospection] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        cached = self._cache.get(token)
        if cached and cached.expires_at > time.time():
            return cached.access_token

        if not self.introspection_endpoint.startswith(
            ("https://", "http://localhost", "http://127.0.0.1")
        ):
            logger.warning(
                f"Rejecting introspection endpoint with unsafe scheme: "
                f"{self.introspection_endpoint}"
            )
            return None

        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
            try:
                response = await client.post(
                    self.introspection_endpoint,
                    data={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code != 200:
                    logger.debug(
                        f"Token introspection returned status {response.status_code}"
                    )
                    return None

                data = response.json()
                if not data.get("active", False):
                    return None

                access_token = AccessToken(
                    token=token,
                    client_id=data.get("client_id", "unknown"),
                    scopes=data.get("scope", "").split() if data.get("scope") else [],
                    expires_at=data.get("exp"),
                    resource=data.get("aud"),
                )

                self._cache[token] = CachedIntrospection(
                    access_token=access_token,
                    api_key=data.get("api_key"),
                    credits_remaining=data.get("credits_remaining"),
                    user_id=data.get("sub"),
                    expires_at=time.time() + CACHE_TTL,
                )

                return access_token

            except Exception as e:
                logger.warning(f"Token introspection failed: {e}")
                return None

    def get_user_context(self, token: str) -> CachedIntrospection | None:
        """Retrieve cached introspection data (api_key, credits, user_id) for a verified token."""
        cached = self._cache.get(token)
        if cached and cached.expires_at > time.time():
            return cached
        return None
