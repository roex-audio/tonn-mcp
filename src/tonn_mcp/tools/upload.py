"""get_upload_url tool."""

import httpx

from tonn_mcp.response import build_envelope


async def call_upload(
    filename: str,
    content_type: str,
    api_key: str,
    api_base: str,
    credits_remaining: int | None,
) -> str:
    url = api_base.rstrip("/") + "/upload"

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.post(
            url,
            json={"filename": filename, "contentType": content_type},
            params={"key": api_key},
        )

    data = resp.json()

    if resp.status_code != 200 or data.get("error"):
        return build_envelope(
            summary="Failed to generate upload URL: " + data.get("message", "Unknown error"),
            data=data,
            credits_remaining=credits_remaining,
        )

    return build_envelope(
        summary="Upload URL generated for '" + filename + "'. PUT your file to the signed_url within 1 hour.",
        data={
            "signed_url": data.get("signed_url"),
            "readable_url": data.get("readable_url"),
            "expires_in": "1 hour",
        },
        next_actions=[
            {"tool": "analyse_mix", "description": "Analyse this track"},
            {"tool": "master_track", "description": "Master this track"},
        ],
        credits_remaining=credits_remaining,
        credits_charged=0,
    )
