"""get_account_status tool."""

from tonn_mcp.response import build_envelope


def build_account_response(
    user_id: str | None,
    credits_remaining: int | None,
) -> str:
    credits_text = str(credits_remaining) if credits_remaining is not None else "unknown"
    return build_envelope(
        summary="Account status retrieved. You have " + credits_text + " credits remaining.",
        data={
            "user_id": user_id,
            "credits_remaining": credits_remaining,
        },
        next_actions=[
            {"tool": "analyse_mix", "description": "Analyse a mix or master"},
            {"tool": "master_track", "description": "Master a track"},
        ],
        credits_remaining=credits_remaining,
        credits_charged=0,
    )
