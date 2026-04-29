"""get_job_status tool."""

import httpx

from tonn_mcp.response import build_envelope

_TASK_TYPE_ENDPOINTS = {
    "mastering": "/retrievepreviewmaster",
    "mix": "/retrievepreviewmix",
    "enhance": "/retrieverevivedtrack",
    "postprod_dialogue": "/postprod/dialogue-enhancement/retrieve-preview",
    "postprod_delivery": "/postprod/delivery-mastering/retrieve-preview",
    "loudness_check": "/postprod/loudness-check/retrieve-preview",
}


async def call_get_job_status(
    task_id: str,
    task_type: str,
    api_key: str,
    api_base: str,
    credits_remaining: int | None,
) -> str:
    endpoint = _TASK_TYPE_ENDPOINTS.get(task_type)
    if not endpoint:
        valid_types = ", ".join(_TASK_TYPE_ENDPOINTS.keys())
        return build_envelope(
            summary="Unknown task_type '" + task_type + "'. Valid types: " + valid_types,
            data={"error": True},
            credits_remaining=credits_remaining,
        )

    url = api_base.rstrip("/") + endpoint

    wrapper_key, id_key = {
        "mastering": ("masteringData", "masteringTaskId"),
        "mix": ("multitrackData", "multitrackMixTaskId"),
        "enhance": ("mixReviveData", "mixReviveTaskId"),
        "postprod_dialogue": ("taskData", "taskId"),
        "postprod_delivery": ("taskData", "taskId"),
        "loudness_check": ("taskData", "taskId"),
    }.get(task_type, ("taskData", "taskId"))

    payload = {wrapper_key: {id_key: task_id}}

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.post(url, json=payload, params={"key": api_key})

    data = resp.json()

    if resp.status_code == 202:
        return build_envelope(
            summary="Job is still processing. Try again in a few seconds.",
            data={"task_id": task_id, "task_type": task_type, "status": "processing"},
            next_actions=[
                {"tool": "get_job_status", "description": "Check again"},
            ],
            credits_remaining=credits_remaining,
        )

    if resp.status_code == 200 and not data.get("error"):
        return build_envelope(
            summary="Job complete. Results are in the data field.",
            data=data,
            credits_remaining=credits_remaining,
        )

    return build_envelope(
        summary="Job status check returned an error: " + data.get("message", "Unknown"),
        data=data,
        credits_remaining=credits_remaining,
    )
