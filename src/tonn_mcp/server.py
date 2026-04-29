"""Tonn MCP Server -- exposes RoEx audio processing tools via Model Context Protocol."""

import contextlib
import logging
import os

from urllib.parse import urlparse

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from tonn_mcp.auth import TonnTokenVerifier

logger = logging.getLogger(__name__)

PORTAL_URL = os.environ.get("TONN_MCP_PORTAL_URL", "http://localhost:5000")
API_URL = os.environ.get("TONN_MCP_API_URL", "https://tonn.roexaudio.com")
SERVER_URL = os.environ.get("TONN_MCP_SERVER_URL", "http://localhost:8080")

_verifier = TonnTokenVerifier(
    introspection_endpoint=PORTAL_URL.rstrip("/") + "/introspect",
)

_server_host = urlparse(SERVER_URL).netloc

mcp = FastMCP(
    "Tonn",
    instructions=(
        "RoEx Tonn audio processing tools. Analyse mixes and master tracks using "
        "publicly accessible audio URLs (e.g. Dropbox, Google Drive, S3). "
        "All charged operations require explicit user confirmation."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    token_verifier=_verifier,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(PORTAL_URL),
        resource_server_url=AnyHttpUrl(SERVER_URL),
        required_scopes=["read:account"],
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[_server_host],
    ),
)


def _get_user_context():
    """Get cached introspection data for the current request's token."""
    access_token = get_access_token()
    if access_token:
        return _verifier.get_user_context(access_token.token)
    return None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_account_status() -> str:
    """Get your Tonn account status including credit balance."""
    from tonn_mcp.tools.account import build_account_response

    ctx = _get_user_context()
    return build_account_response(
        user_id=ctx.user_id if ctx else None,
        credits_remaining=ctx.credits_remaining if ctx else None,
    )


@mcp.tool()
async def analyse_mix(
    track_url: str,
    musical_style: str,
    is_master: bool = False,
    confirm_charge: bool = False,
) -> str:
    """Analyse a mix or master for loudness, frequency balance, stereo width, dynamics, and issues.

    track_url must be a publicly accessible URL to an audio file (wav, mp3, flac, aiff).
    Users can host files on Dropbox, Google Drive (use direct download link), S3, or any
    public URL. Ask the user for their audio URL if they haven't provided one.

    This charges credits. You MUST set confirm_charge=true to proceed.
    musical_style (lowercase): rock, pop, electronic, hip_hop_grime, acoustic, blues,
    jazz, soul, folk, punk, ambient, experimental, country, funk, rnb, indie_pop,
    indie_rock, house, trap, techno, orchestral, afrobeat, drum_n_bass, trance,
    lo_fi, reggae, latin, metal, dance, instrumental.
    """
    if not confirm_charge:
        return '{"error": "confirm_charge must be true to proceed. This operation charges credits."}'

    ctx = _get_user_context()
    if not ctx or not ctx.api_key:
        return '{"error": "Not authenticated or missing API key"}'

    from tonn_mcp.tools.analysis import call_analyse_mix

    return await call_analyse_mix(
        track_url=track_url,
        musical_style=musical_style,
        is_master=is_master,
        api_key=ctx.api_key,
        api_base=API_URL,
        credits_remaining=ctx.credits_remaining,
    )


@mcp.tool()
async def master_track(
    track_url: str,
    musical_style: str,
    desired_loudness: str = "MEDIUM",
    sample_rate: int = 44100,
    final: bool = False,
    confirm_charge: bool = False,
) -> str:
    """Master a track. Returns a free 30-second preview by default.

    track_url must be a publicly accessible URL to an audio file (wav, mp3, flac, aiff).
    Users can host files on Dropbox, Google Drive (use direct download link), S3, or any
    public URL. Ask the user for their audio URL if they haven't provided one.

    Set final=true and confirm_charge=true to retrieve the full master (charges credits).
    desired_loudness: LOW, MEDIUM, HIGH.
    musical_style (UPPERCASE): ROCK_INDIE, POP, ACOUSTIC, HIPHOP_GRIME, ELECTRONIC,
    REGGAE_DUB, METAL, OTHER.
    """
    if final and not confirm_charge:
        return '{"error": "confirm_charge must be true when final=true. Final mastering charges credits."}'

    ctx = _get_user_context()
    if not ctx or not ctx.api_key:
        return '{"error": "Not authenticated or missing API key"}'

    from tonn_mcp.tools.mastering import call_master_track

    return await call_master_track(
        track_url=track_url,
        musical_style=musical_style,
        desired_loudness=desired_loudness,
        sample_rate=sample_rate,
        final=final,
        api_key=ctx.api_key,
        api_base=API_URL,
        credits_remaining=ctx.credits_remaining,
    )


@mcp.tool()
async def get_job_status(task_id: str, task_type: str) -> str:
    """Check the status of a long-running processing job.

    task_type: mastering, mix, enhance, postprod_dialogue, postprod_delivery, loudness_check.
    """
    ctx = _get_user_context()
    if not ctx or not ctx.api_key:
        return '{"error": "Not authenticated or missing API key"}'

    from tonn_mcp.tools.status import call_get_job_status

    return await call_get_job_status(
        task_id=task_id,
        task_type=task_type,
        api_key=ctx.api_key,
        api_base=API_URL,
        credits_remaining=ctx.credits_remaining,
    )


# ---------------------------------------------------------------------------
# Origin validation middleware
# ---------------------------------------------------------------------------

ALLOWED_ORIGINS = {
    "https://claude.ai",
    "https://api.anthropic.com",
    "https://console.anthropic.com",
}


class OriginValidationMiddleware:
    """Reject requests from disallowed origins in production.

    Discovery endpoints (/.well-known/*) are exempt so that any client
    can perform RFC 9728 resource discovery.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if not path.startswith("/.well-known"):
                headers = dict(scope.get("headers", []))
                origin = headers.get(b"origin", b"").decode()
                if origin and origin not in ALLOWED_ORIGINS:
                    response = JSONResponse(
                        {"error": "origin_not_allowed"}, status_code=403
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# ASGI app for deployment
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(application: Starlette):
    async with mcp.session_manager.run():
        logger.info("Tonn MCP server started")
        yield
        logger.info("Tonn MCP server stopping")


app = Starlette(
    routes=[
        Mount("/", app=mcp.streamable_http_app()),
    ],
    middleware=[Middleware(OriginValidationMiddleware)],
    lifespan=lifespan,
)


def main():
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Tonn MCP server on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
