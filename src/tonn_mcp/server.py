"""Tonn MCP Server -- exposes RoEx audio processing tools via Model Context Protocol."""

import contextlib
import logging
import os

from urllib.parse import urlparse

from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
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
        "RoEx Tonn audio processing tools. You can analyse mixes, master tracks, "
        "and upload audio files. All charged operations require explicit confirmation."
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
async def upload_file(
    filename: str,
    file_data_base64: str = "",
    file_url: str = "",
) -> str:
    """Upload an audio file to Tonn for processing.

    Provide the file as base64 data OR a URL where the file can be fetched.
    Supported formats: wav, mp3, flac, aiff.
    """
    from tonn_mcp.tools.upload import call_upload_and_transfer

    ctx = _get_user_context()
    if not ctx or not ctx.api_key:
        return '{"error": "Not authenticated or missing API key"}'

    return await call_upload_and_transfer(
        filename=filename,
        file_data_base64=file_data_base64 or None,
        file_url=file_url or None,
        api_key=ctx.api_key,
        api_base=API_URL,
        credits_remaining=ctx.credits_remaining,
    )


@mcp.tool()
async def analyse_mix(
    track_url: str,
    musical_style: str,
    is_master: bool = False,
    confirm_charge: bool = False,
) -> str:
    """Analyse a mix or master for loudness, frequency balance, stereo width, dynamics, and issues.

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
            if not path.startswith("/.well-known") and not path.startswith("/upload"):
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
# REST upload endpoint (for files too large for MCP tool call args)
# ---------------------------------------------------------------------------

UPLOAD_PAGE_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Tonn – Upload Audio</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0a0a0a;color:#e5e5e5;
display:flex;justify-content:center;align-items:center;min-height:100vh}
.card{background:#1a1a1a;border:1px solid #333;border-radius:12px;padding:2.5rem;
max-width:480px;width:100%}
h1{font-size:1.4rem;margin-bottom:.5rem}
p{color:#999;font-size:.9rem;margin-bottom:1.5rem}
.drop{border:2px dashed #444;border-radius:8px;padding:3rem 1rem;text-align:center;
cursor:pointer;transition:border-color .2s}
.drop.over{border-color:#6366f1}
.drop input{display:none}
.drop label{cursor:pointer;color:#6366f1}
#status{margin-top:1rem;font-size:.85rem;word-break:break-all}
.url-box{background:#111;border:1px solid #333;border-radius:6px;padding:.75rem;
margin-top:.75rem;font-family:monospace;font-size:.8rem;user-select:all}
button{background:#6366f1;color:#fff;border:none;border-radius:6px;padding:.5rem 1rem;
cursor:pointer;margin-top:.75rem;font-size:.85rem}
button:hover{background:#4f46e5}
</style></head><body>
<div class="card">
<h1>Upload Audio to Tonn</h1>
<p>Drop a file here, then paste the URL into Claude.</p>
<div class="drop" id="drop">
<p>Drag & drop audio file here</p>
<p style="margin-top:.5rem">or <label for="file">browse</label></p>
<input type="file" id="file" accept=".wav,.mp3,.flac,.aiff,.aif">
</div>
<div id="status"></div>
</div>
<script>
const drop=document.getElementById('drop'),file=document.getElementById('file'),
status=document.getElementById('status');
drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('over')});
drop.addEventListener('dragleave',()=>drop.classList.remove('over'));
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('over');
if(e.dataTransfer.files.length)upload(e.dataTransfer.files[0])});
file.addEventListener('change',()=>{if(file.files.length)upload(file.files[0])});
async function upload(f){
status.innerHTML='Uploading '+f.name+'...';
const fd=new FormData();fd.append('file',f);
try{
const r=await fetch('/upload',{method:'POST',body:fd});
const d=await r.json();
if(d.track_url){
status.innerHTML='Ready! Paste this URL into Claude:<div class="url-box">'+d.track_url+
'</div><button onclick="navigator.clipboard.writeText(\\''+d.track_url+
'\\')">Copy URL</button>';
}else{status.innerHTML='Error: '+(d.error||JSON.stringify(d))}
}catch(e){status.innerHTML='Upload failed: '+e.message}
}
</script></body></html>"""


async def upload_page(request: Request):
    return HTMLResponse(UPLOAD_PAGE_HTML)


async def handle_upload(request: Request):
    """Accept multipart file upload, push to GCS via Tonn API, return track_url."""
    import httpx

    auth_header = request.headers.get("authorization", "")
    # For browser uploads, check for a cookie-based session or allow if from same origin
    # For simplicity, use the API key from a query param or header
    api_key = request.query_params.get("key", "")

    if not api_key:
        # Try to get API key from Bearer token via introspection
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            cached = _verifier._cache.get(token)
            if cached:
                api_key = cached.api_key or ""

    if not api_key:
        return JSONResponse({"error": "API key required. Pass ?key=YOUR_API_KEY"}, status_code=401)

    form = await request.form()
    uploaded = form.get("file")
    if not uploaded:
        return JSONResponse({"error": "No file provided"}, status_code=400)

    filename = uploaded.filename
    file_bytes = await uploaded.read()

    from tonn_mcp.tools.upload import _guess_content_type
    content_type = _guess_content_type(filename)
    if not content_type:
        return JSONResponse({"error": f"Unsupported file type: {filename}"}, status_code=400)

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            API_URL.rstrip("/") + "/upload",
            json={"filename": filename, "contentType": content_type},
            params={"key": api_key},
        )
        try:
            data = resp.json()
        except Exception:
            return JSONResponse({"error": "Tonn API error", "status": resp.status_code}, status_code=502)

        if resp.status_code != 200 or data.get("error"):
            return JSONResponse({"error": data.get("message", "Upload URL failed")}, status_code=502)

        signed_url = data.get("signed_url")
        readable_url = data.get("readable_url")

        put_resp = await client.put(
            signed_url,
            content=file_bytes,
            headers={"Content-Type": content_type},
            timeout=httpx.Timeout(120.0, connect=10.0),
        )
        if put_resp.status_code not in (200, 201):
            return JSONResponse({"error": f"GCS upload failed ({put_resp.status_code})"}, status_code=502)

    return JSONResponse({
        "track_url": readable_url,
        "filename": filename,
        "size_bytes": len(file_bytes),
    })


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
        Route("/upload", upload_page, methods=["GET"]),
        Route("/upload", handle_upload, methods=["POST"]),
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
