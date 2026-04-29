"""analyse_mix tool."""

import httpx

from tonn_mcp.response import build_envelope, summarise_mix_analysis


async def call_analyse_mix(
    track_url: str,
    musical_style: str,
    is_master: bool,
    api_key: str,
    api_base: str,
    credits_remaining: int | None,
) -> str:
    url = api_base.rstrip("/") + "/mixanalysis"

    payload = {
        "mixDiagnosisData": {
            "audioFileLocation": track_url,
            "musicalStyle": musical_style,
            "isMaster": is_master,
        }
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        resp = await client.post(
            url,
            json=payload,
            params={"key": api_key},
        )

    data = resp.json()

    if resp.status_code != 200 or data.get("error"):
        return build_envelope(
            summary="Mix analysis failed: " + data.get("message", "Unknown error"),
            data=data,
            credits_remaining=credits_remaining,
        )

    summary = summarise_mix_analysis(data)

    return build_envelope(
        summary=summary,
        data=data,
        next_actions=[
            {"tool": "master_track", "description": "Master this track based on the analysis"},
        ],
        credits_remaining=credits_remaining,
        credits_charged=data.get("credits_charged", 0),
    )
