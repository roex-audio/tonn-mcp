"""Async polling loop with exponential backoff for Tonn retrieve endpoints."""

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BACKOFF_SCHEDULE = [2, 4, 8, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10]
TOTAL_BUDGET = 180  # 3 minutes


async def poll_retrieve(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    api_base: str,
) -> tuple[dict[str, Any] | None, bool]:
    """Poll a Tonn retrieve endpoint until complete or budget exhausted.

    Returns (result_data, is_complete). If budget is exhausted, is_complete=False
    and result_data contains the task_id for follow-up via get_job_status.
    """
    full_url = api_base.rstrip("/") + url
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for delay in BACKOFF_SCHEDULE:
            elapsed = time.monotonic() - start
            if elapsed >= TOTAL_BUDGET:
                break

            try:
                resp = await client.post(
                    full_url,
                    json=payload,
                    params={"key": api_key},
                )

                if resp.status_code == 200:
                    data = resp.json()
                    if not data.get("error", False):
                        return data, True

                if resp.status_code == 202:
                    logger.debug("Job still processing, polling again in %ds", delay)
                elif resp.status_code != 200:
                    logger.warning(
                        "Retrieve returned %d: %s", resp.status_code, resp.text[:200]
                    )
                    return {"error": True, "status_code": resp.status_code}, True

            except httpx.TimeoutException:
                logger.warning("Retrieve request timed out, retrying")

            await asyncio.sleep(delay)

    return None, False
