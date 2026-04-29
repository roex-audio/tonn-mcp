"""Tests for the response envelope builder and mix analysis summariser."""

import json

from tonn_mcp.response import build_envelope, summarise_mix_analysis


class TestBuildEnvelope:
    def test_basic_structure(self):
        result = build_envelope(
            summary="Test summary",
            data={"key": "value"},
            credits_remaining=100,
            credits_charged=5,
        )
        parsed = json.loads(result)
        assert parsed["summary"] == "Test summary"
        assert parsed["data"] == {"key": "value"}
        assert parsed["next_actions"] == []
        assert parsed["credits_remaining"] == 100
        assert parsed["credits_charged"] == 5

    def test_with_next_actions(self):
        actions = [{"tool": "analyse_mix", "description": "Analyse track"}]
        result = build_envelope(
            summary="Done",
            data={},
            next_actions=actions,
        )
        parsed = json.loads(result)
        assert len(parsed["next_actions"]) == 1
        assert parsed["next_actions"][0]["tool"] == "analyse_mix"

    def test_none_credits(self):
        result = build_envelope(summary="X", data={})
        parsed = json.loads(result)
        assert parsed["credits_remaining"] is None
        assert parsed["credits_charged"] == 0


class TestSummariseMixAnalysis:
    def test_loud_master(self):
        analysis = {
            "if_master_loudness": "MORE",
            "tonal_profile": {},
            "stereo_field": "OK",
        }
        summary = summarise_mix_analysis(analysis)
        assert "louder than optimal" in summary
        assert "master" in summary

    def test_quiet_mix(self):
        analysis = {
            "if_mix_loudness": "LESS",
            "tonal_profile": {},
        }
        summary = summarise_mix_analysis(analysis)
        assert "quieter than optimal" in summary
        assert "mix" in summary

    def test_tonal_issues(self):
        analysis = {
            "tonal_profile": {
                "bass_frequency": "HIGH",
                "high_frequency": "LOW",
                "low_mid_frequency": "OK",
                "high_mid_frequency": "OK",
            },
        }
        summary = summarise_mix_analysis(analysis)
        assert "excessive" in summary
        assert "low-end" in summary
        assert "lacking" in summary
        assert "high-end" in summary

    def test_balanced_tonal(self):
        analysis = {
            "tonal_profile": {
                "bass_frequency": "OK",
                "low_mid_frequency": "OK",
                "high_mid_frequency": "OK",
                "high_frequency": "OK",
            },
        }
        summary = summarise_mix_analysis(analysis)
        assert "even across the spectrum" in summary

    def test_clipping_and_phase(self):
        analysis = {
            "is_clipping": True,
            "phase_issues": True,
            "mono_compatibility": False,
            "tonal_profile": {},
        }
        summary = summarise_mix_analysis(analysis)
        assert "clipping detected" in summary
        assert "phase issues" in summary
        assert "mono compatibility" in summary

    def test_no_issues(self):
        analysis = {
            "is_clipping": False,
            "phase_issues": False,
            "tonal_profile": {},
        }
        summary = summarise_mix_analysis(analysis)
        assert "No clipping or phase issues" in summary

    def test_stereo_wide(self):
        analysis = {"stereo_field": "WIDE", "tonal_profile": {}}
        summary = summarise_mix_analysis(analysis)
        assert "wider than typical" in summary

    def test_stereo_narrow(self):
        analysis = {"stereo_field": "NARROW", "tonal_profile": {}}
        summary = summarise_mix_analysis(analysis)
        assert "narrower than typical" in summary

    def test_dynamic_range_compressed(self):
        analysis = {"if_master_drc": "MORE", "tonal_profile": {}}
        summary = summarise_mix_analysis(analysis)
        assert "heavily compressed" in summary

    def test_dynamic_range_wide(self):
        analysis = {"if_mix_drc": "LESS", "tonal_profile": {}}
        summary = summarise_mix_analysis(analysis)
        assert "wider than usual" in summary
