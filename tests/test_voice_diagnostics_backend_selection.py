"""Diagnostics must select the same backend aliases as the backend factory."""

import asyncio

import pytest
from test_voice_operations import make_agent

from voice_agent import diagnostics
from voice_agent.backends.mimo_cascade import MimoCascadeBackend
from voice_agent.voice_control import VoiceControlDecision


@pytest.mark.parametrize("backend", [" MIMO ", " MiMo_Cascade ", " CASCADE_MIMO "])
def test_network_diagnostics_accept_normalized_mimo_aliases(tmp_path, monkeypatch, backend):
    async def classify(self, text):
        return VoiceControlDecision()

    monkeypatch.setattr(MimoCascadeBackend, "detect_control_intent", classify)
    agent = make_agent(tmp_path)
    agent.settings.backend = backend
    agent.settings.mimo_api_key = "diagnostic-test"
    agent.settings.gemini_api_key = ""
    agent.settings.gemini_base_url = ""

    result = asyncio.run(diagnostics.diagnose(agent, network=True))

    checks = {item["id"]: item for item in result["checks"]}
    assert checks["credentials"]["state"] == "pass"
    assert checks["network"]["state"] == "pass"
    assert result["network_checked"]
