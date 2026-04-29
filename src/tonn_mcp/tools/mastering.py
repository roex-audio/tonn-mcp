"""master_track tool."""

import httpx

from tonn_mcp.polling import poll_retrieve
from tonn_mcp.response import build_envelope


async def call_master_track(
    track_url: str,
    musical_style: str,
    desired_loudness: str,
    sample_rate: int,
    final: bool,
    api_key: str,
    api_base: str,
    credits_remaining: int | None,
) -> str:
    preview_url = api_base.rstrip("/") + "/masteringpreview"

    payload = {
        "masteringData": {
            "trackData": [{"trackURL": track_url}],
            "musicalStyle": musical_style,
            "desiredLoudness": desired_loudness,
            "sampleRate": str(sample_rate),
        }
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            preview_url,
            json=payload,
            params={"key": api_key},
        )

    data = resp.json()

    if resp.status_code != 200 or data.get("error"):
        return build_envelope(
            summary="Mastering request failed: " + data.get("message", "Unknown error"),
            data=data,
            credits_remaining=credits_remaining,
        )

    task_id = data.get("masteringTaskId") or data.get("task_id")

    retrieve_payload = {"masteringData": {"masteringTaskId": task_id}}
    result, is_complete = await poll_retrieve(
        url="/retrievepreviewmaster",
        payload=retrieve_payload,
        api_key=api_key,
        api_base=api_base,
    )

    if not is_complete:
        return build_envelope(
            summary="Mastering is still processing. Use get_job_status to check progress.",
            data={"task_id": task_id, "task_type": "mastering", "status": "processing"},
            next_actions=[
                {"tool": "get_job_status", "description": "Check mastering job status"},
            ],
            credits_remaining=credits_remaining,
        )

    if result and result.get("error"):
        return build_envelope(
            summary="Mastering preview failed: " + result.get("message", "Unknown error"),
            data=result,
            credits_remaining=credits_remaining,
        )

    if final:
        final_result = await _retrieve_final_master(task_id, api_key, api_base)
        if final_result.get("error"):
            return build_envelope(
                summary="Final master retrieval failed: " + final_result.get("message", ""),
                data=final_result,
                credits_remaining=credits_remaining,
            )

        return build_envelope(
            summary="Final master ready. Download URL is in the data.",
            data=final_result,
            next_actions=[
                {"tool": "analyse_mix", "description": "Analyse the mastered track"},
            ],
            credits_remaining=credits_remaining,
            credits_charged=final_result.get("credits_charged", 0),
        )

    return build_envelope(
        summary="30-second mastering preview is ready. Set final=true and confirm_charge=true to get the full master.",
        data=result,
        next_actions=[
            {"tool": "master_track", "description": "Get the full final master (charges credits)"},
            {"tool": "analyse_mix", "description": "Analyse the preview"},
        ],
        credits_remaining=credits_remaining,
        credits_charged=0,
    )


async def _retrieve_final_master(
    task_id: str,
    api_key: str,
    api_base: str,
) -> dict:
    url = api_base.rstrip("/") + "/retrievefinalmaster"
    payload = {"masteringData": {"masteringTaskId": task_id}}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(url, json=payload, params={"key": api_key})

    return resp.json()
