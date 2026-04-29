"""Response envelope builder for MCP tools with mix analysis summary translation."""

import json
from typing import Any


def build_envelope(
    summary: str,
    data: dict[str, Any],
    next_actions: list[dict[str, str]] | None = None,
    credits_remaining: int | None = None,
    credits_charged: int = 0,
) -> str:
    envelope = {
        "summary": summary,
        "data": data,
        "next_actions": next_actions or [],
        "credits_remaining": credits_remaining,
        "credits_charged": credits_charged,
    }
    return json.dumps(envelope, indent=2)


_LOUDNESS_LABELS = {
    "MORE": "louder than optimal for streaming",
    "LESS": "quieter than optimal for streaming",
    "OK": "at a good loudness level for streaming",
}

_TONAL_LABELS = {
    "HIGH": "slightly excessive",
    "LOW": "slightly lacking",
    "OK": "well-balanced",
}

_BAND_NAMES = {
    "bass_frequency": "low-end energy",
    "low_mid_frequency": "low-mid energy",
    "high_mid_frequency": "high-mid energy",
    "high_frequency": "high-end energy",
}


def summarise_mix_analysis(analysis: dict) -> str:
    """Translate Tonn mix analysis enums into a conversational summary."""
    parts = []

    loudness = analysis.get("if_master_loudness") or analysis.get("if_mix_loudness")
    if loudness:
        label = _LOUDNESS_LABELS.get(loudness, loudness)
        track_type = "master" if "if_master_loudness" in analysis else "mix"
        parts.append("This " + track_type + " is " + label + ".")

    tonal = analysis.get("tonal_profile", {})
    tonal_issues = []
    for band_key, band_name in _BAND_NAMES.items():
        value = tonal.get(band_key)
        if value and value != "OK":
            label = _TONAL_LABELS.get(value, value)
            tonal_issues.append(label + " " + band_name)

    if tonal_issues:
        parts.append("Frequency balance shows " + ", ".join(tonal_issues) + ".")
    else:
        parts.append("Frequency balance is even across the spectrum.")

    stereo = analysis.get("stereo_field")
    if stereo == "WIDE":
        parts.append("Stereo field is wider than typical.")
    elif stereo == "NARROW":
        parts.append("Stereo field is narrower than typical.")
    elif stereo:
        parts.append("Stereo field is well-balanced.")

    issues = []
    if analysis.get("is_clipping"):
        issues.append("clipping detected")
    if analysis.get("phase_issues"):
        issues.append("phase issues detected")
    if analysis.get("mono_compatibility") is False:
        issues.append("poor mono compatibility")

    if issues:
        parts.append("Potential issues: " + ", ".join(issues) + ".")
    else:
        parts.append("No clipping or phase issues detected.")

    drc = analysis.get("if_master_drc") or analysis.get("if_mix_drc")
    if drc == "MORE":
        parts.append("Dynamic range is heavily compressed.")
    elif drc == "LESS":
        parts.append(
            "Dynamic range is wider than usual; consider light compression."
        )

    return " ".join(parts)
