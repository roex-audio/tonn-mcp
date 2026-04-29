"""Tests for MCP tool functions with mocked httpx responses."""

import json

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from tonn_mcp.tools.account import build_account_response
from tonn_mcp.tools.analysis import call_analyse_mix
from tonn_mcp.tools.mastering import call_master_track
from tonn_mcp.tools.status import call_get_job_status

API_BASE = "https://tonn.roexaudio.com"
API_KEY = "pk_test_abc123"


def _mock_response(status_code=200, data=None):
    return httpx.Response(
        status_code=status_code,
        json=data or {},
        request=httpx.Request("POST", API_BASE),
    )


def _parse(result: str) -> dict:
    return json.loads(result)


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

class TestAccountTool:
    def test_with_credits(self):
        result = build_account_response(user_id="user_1", credits_remaining=5000)
        parsed = _parse(result)
        assert parsed["data"]["credits_remaining"] == 5000
        assert "5000" in parsed["summary"]

    def test_unknown_credits(self):
        result = build_account_response(user_id="user_1", credits_remaining=None)
        parsed = _parse(result)
        assert parsed["data"]["credits_remaining"] is None
        assert "unknown" in parsed["summary"]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalysisTool:
    async def test_success(self):
        analysis_data = {
            "if_mix_loudness": "OK",
            "tonal_profile": {
                "bass_frequency": "OK",
                "low_mid_frequency": "OK",
                "high_mid_frequency": "OK",
                "high_frequency": "OK",
            },
            "stereo_field": "OK",
            "is_clipping": False,
            "phase_issues": False,
            "credits_charged": 10,
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, analysis_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.tools.analysis.httpx.AsyncClient", return_value=mock_client):
            result = await call_analyse_mix(
                track_url="https://storage.example.com/track.wav",
                musical_style="rock",
                is_master=False,
                api_key=API_KEY,
                api_base=API_BASE,
                credits_remaining=990,
            )

        parsed = _parse(result)
        assert parsed["credits_charged"] == 10
        assert "good loudness" in parsed["summary"]

        # Verify endpoint
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://tonn.roexaudio.com/mixanalysis"
        payload = call_args[1]["json"]
        assert payload["mixDiagnosisData"]["audioFileLocation"] == "https://storage.example.com/track.wav"
        assert payload["mixDiagnosisData"]["musicalStyle"] == "rock"

    async def test_api_error(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(500, {"error": True, "message": "Server error"})
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.tools.analysis.httpx.AsyncClient", return_value=mock_client):
            result = await call_analyse_mix(
                track_url="https://storage.example.com/track.wav",
                musical_style="pop",
                is_master=True,
                api_key=API_KEY,
                api_base=API_BASE,
                credits_remaining=100,
            )

        parsed = _parse(result)
        assert "failed" in parsed["summary"].lower()


# ---------------------------------------------------------------------------
# Mastering (preview only, mocking poll_retrieve)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMasteringTool:
    async def test_preview_success(self):
        submit_data = {"masteringTaskId": "task_abc123"}
        preview_data = {
            "previewUrl": "https://storage.example.com/preview.wav",
            "masteringTaskId": "task_abc123",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, submit_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.tools.mastering.httpx.AsyncClient", return_value=mock_client), \
             patch("tonn_mcp.tools.mastering.poll_retrieve", return_value=(preview_data, True)):
            result = await call_master_track(
                track_url="https://storage.example.com/track.wav",
                musical_style="ROCK_INDIE",
                desired_loudness="MEDIUM",
                sample_rate=44100,
                final=False,
                api_key=API_KEY,
                api_base=API_BASE,
                credits_remaining=500,
            )

        parsed = _parse(result)
        assert "preview is ready" in parsed["summary"]
        assert parsed["credits_charged"] == 0

        # Verify payload structure
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://tonn.roexaudio.com/masteringpreview"
        payload = call_args[1]["json"]
        assert payload["masteringData"]["trackData"] == [{"trackURL": "https://storage.example.com/track.wav"}]
        assert payload["masteringData"]["sampleRate"] == "44100"

    async def test_still_processing(self):
        submit_data = {"masteringTaskId": "task_slow"}
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, submit_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.tools.mastering.httpx.AsyncClient", return_value=mock_client), \
             patch("tonn_mcp.tools.mastering.poll_retrieve", return_value=(None, False)):
            result = await call_master_track(
                track_url="https://storage.example.com/track.wav",
                musical_style="POP",
                desired_loudness="HIGH",
                sample_rate=48000,
                final=False,
                api_key=API_KEY,
                api_base=API_BASE,
                credits_remaining=500,
            )

        parsed = _parse(result)
        assert "still processing" in parsed["summary"]
        assert parsed["data"]["task_id"] == "task_slow"


# ---------------------------------------------------------------------------
# Job Status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestJobStatusTool:
    async def test_complete(self):
        result_data = {
            "previewUrl": "https://storage.example.com/preview.wav",
            "masteringTaskId": "task_done",
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, result_data)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.tools.status.httpx.AsyncClient", return_value=mock_client):
            result = await call_get_job_status(
                task_id="task_done",
                task_type="mastering",
                api_key=API_KEY,
                api_base=API_BASE,
                credits_remaining=500,
            )

        parsed = _parse(result)
        assert "complete" in parsed["summary"].lower()

        # Verify payload wrapping
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://tonn.roexaudio.com/retrievepreviewmaster"
        payload = call_args[1]["json"]
        assert payload == {"masteringData": {"masteringTaskId": "task_done"}}

    async def test_still_processing(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(202, {})
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.tools.status.httpx.AsyncClient", return_value=mock_client):
            result = await call_get_job_status(
                task_id="task_pending",
                task_type="mix",
                api_key=API_KEY,
                api_base=API_BASE,
                credits_remaining=500,
            )

        parsed = _parse(result)
        assert "processing" in parsed["summary"].lower()

        # Verify mix payload wrapping
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload == {"multitrackData": {"multitrackMixTaskId": "task_pending"}}

    async def test_unknown_task_type(self):
        result = await call_get_job_status(
            task_id="task_x",
            task_type="unknown_type",
            api_key=API_KEY,
            api_base=API_BASE,
            credits_remaining=500,
        )
        parsed = _parse(result)
        assert "Unknown" in parsed["summary"]
        assert parsed["data"]["error"] is True

    async def test_enhance_payload_structure(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(200, {"result": "ok"})
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("tonn_mcp.tools.status.httpx.AsyncClient", return_value=mock_client):
            await call_get_job_status(
                task_id="task_enhance",
                task_type="enhance",
                api_key=API_KEY,
                api_base=API_BASE,
                credits_remaining=500,
            )

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://tonn.roexaudio.com/retrieverevivedtrack"
        payload = call_args[1]["json"]
        assert payload == {"mixReviveData": {"mixReviveTaskId": "task_enhance"}}
