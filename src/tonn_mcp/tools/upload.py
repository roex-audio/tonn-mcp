"""upload_file tool — get a signed URL from the Tonn API then PUT the file to GCS."""

import base64
import mimetypes
import os

import httpx

from tonn_mcp.response import build_envelope

CONTENT_TYPE_MAP = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
}


def _guess_content_type(filename: str) -> str | None:
    ext = os.path.splitext(filename)[1].lower()
    return CONTENT_TYPE_MAP.get(ext)


async def call_upload_and_transfer(
    filename: str,
    file_data_base64: str | None,
    file_url: str | None,
    api_key: str,
    api_base: str,
    credits_remaining: int | None,
) -> str:
    content_type = _guess_content_type(filename)
    if not content_type:
        return build_envelope(
            summary=f"Unsupported file type for '{filename}'. Supported: wav, mp3, flac, aiff.",
            data={"error": "unsupported_file_type"},
            credits_remaining=credits_remaining,
        )

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Step 1: Get signed upload URL from Tonn API
        resp = await client.post(
            api_base.rstrip("/") + "/upload",
            json={"filename": filename, "contentType": content_type},
            params={"key": api_key},
        )

        try:
            data = resp.json()
        except Exception:
            return build_envelope(
                summary="Tonn API returned an invalid response when requesting upload URL.",
                data={"status": resp.status_code, "body": resp.text[:500]},
                credits_remaining=credits_remaining,
            )

        if resp.status_code != 200 or data.get("error"):
            return build_envelope(
                summary="Failed to get upload URL: " + data.get("message", "Unknown error"),
                data=data,
                credits_remaining=credits_remaining,
            )

        signed_url = data.get("signed_url")
        readable_url = data.get("readable_url")

        if not signed_url:
            return build_envelope(
                summary="Tonn API did not return a signed upload URL.",
                data=data,
                credits_remaining=credits_remaining,
            )

        # Step 2: Get the file bytes
        if file_data_base64:
            file_bytes = base64.b64decode(file_data_base64)
        elif file_url:
            dl = await client.get(file_url, follow_redirects=True)
            if dl.status_code != 200:
                return build_envelope(
                    summary=f"Failed to download file from URL (HTTP {dl.status_code}).",
                    data={"url": file_url},
                    credits_remaining=credits_remaining,
                )
            file_bytes = dl.content
        else:
            return build_envelope(
                summary="No file data provided. Supply file_data_base64 or file_url.",
                data={"error": "no_file_data"},
                credits_remaining=credits_remaining,
            )

        # Step 3: PUT the file to the signed GCS URL
        put_timeout = httpx.Timeout(120.0, connect=10.0)
        put_resp = await client.put(
            signed_url,
            content=file_bytes,
            headers={"Content-Type": content_type},
            timeout=put_timeout,
        )

        if put_resp.status_code not in (200, 201):
            return build_envelope(
                summary=f"File upload to storage failed (HTTP {put_resp.status_code}).",
                data={"status": put_resp.status_code},
                credits_remaining=credits_remaining,
            )

    return build_envelope(
        summary=f"'{filename}' uploaded successfully. Use the track_url below with analyse_mix or master_track.",
        data={
            "track_url": readable_url,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(file_bytes),
        },
        next_actions=[
            {"tool": "analyse_mix", "description": "Analyse this track"},
            {"tool": "master_track", "description": "Master this track"},
        ],
        credits_remaining=credits_remaining,
        credits_charged=0,
    )
