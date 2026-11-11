from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from test_live_speaker_streaming import make_backend, until

from voice_agent.backends.live_speakers import SpeakerInput


def test_speaker_status_is_bounded_detached_and_contains_only_metadata(tmp_path):
    async def run():
        backend = make_backend(tmp_path)
        backend._members = {"a": "Alice"}
        backend._states = lambda: {"a": {"cid": 7, "sender_uid": "7"}}
        backend.settings.gemini_api_key = "private-key-must-not-appear"
        backend._last_user_text = "private-transcript-must-not-appear"
        backend._input = SpeakerInput("7", "a", "Alice", 16000)
        for _ in range(45):
            backend._record_speaker_event("input_start")
        status = backend.speaker_status()
        assert status["current"]["oopz_uid"] == "a"
        assert status["current"]["confirmed"]
        assert len(status["recent_events"]) == 40
        serialized = json.dumps(status)
        assert "private-key" not in serialized and "private-transcript" not in serialized
        status["recent_events"].clear()
        status["mappings"][0]["display_name"] = "changed"
        fresh = backend.speaker_status()
        assert len(fresh["recent_events"]) == 40
        assert fresh["mappings"][0]["display_name"] == "Alice"
        await backend.close()

    asyncio.run(run())


def test_reconnecting_input_does_not_bypass_retry_budget(tmp_path, monkeypatch):
    async def run():
        backend = make_backend(tmp_path)
        backend._connection_state = "reconnecting"
        calls = []

        async def stream(turn):
            calls.append(turn.rtc_uid)

        monkeypatch.setattr(backend, "_stream_input", stream)
        await backend.push_room_audio("7", b"\x00\x20" * 640, 16000)
        backend._ensure_input_worker()
        await asyncio.sleep(0.03)
        assert calls == []
        backend._connection_state = "ready"
        await until(lambda: calls == ["7"])
        await backend.close()

    asyncio.run(run())


def test_failed_connection_discards_pending_speech(tmp_path):
    async def run():
        backend = make_backend(tmp_path)
        await backend.push_room_audio("7", b"\x00\x20" * 640, 16000)
        backend._connection_state = "failed"
        backend._ensure_input_worker()
        await until(lambda: backend._pending_input is None)
        assert backend._collecting is None
        assert backend.speaker_status()["phase"] == "failed"
        await backend.close()

    asyncio.run(run())


def test_continuously_late_transcription_has_a_drain_deadline(tmp_path, monkeypatch):
    from voice_agent.backends import live_speakers

    async def run():
        backend = make_backend(tmp_path)
        backend._ws = SimpleNamespace(closed=False)
        monkeypatch.setattr(live_speakers, "_LATE_TRANSCRIPTION_SECONDS", 0)
        monkeypatch.setattr(live_speakers, "MAX_TRANSCRIPTION_DRAIN_SECONDS", 0.01, raising=False)

        async def start():
            pass

        async def send(message):
            if "activityEnd" in message.get("realtimeInput", {}):
                backend._response_done.set()
                backend._last_server_input = time.monotonic() + 10

        monkeypatch.setattr(backend, "start_session", start)
        monkeypatch.setattr(backend, "_send", send)
        turn = SpeakerInput("7", "", "", 16000, ended=True)
        with pytest.raises(TimeoutError, match="transcription drain timed out"):
            await asyncio.wait_for(backend._stream_input(turn), 2)
        await backend.close()

    asyncio.run(run())


def test_input_error_clears_windows_and_records_a_safe_error_kind(tmp_path, monkeypatch):
    async def run():
        backend = make_backend(tmp_path)
        scheduled = []
        backend._conversation._deadlines["old-member"] = time.monotonic() + 30

        async def start():
            pass

        async def send(message):
            raise RuntimeError("private-authenticated-url")

        monkeypatch.setattr(backend, "start_session", start)
        monkeypatch.setattr(backend, "_send", send)
        monkeypatch.setattr(backend, "_schedule_reconnect", lambda: scheduled.append(True))
        await backend.push_room_audio("7", b"\x00\x20" * 640, 16000)
        backend._ensure_input_worker()
        await until(lambda: bool(scheduled))
        status = backend.speaker_status()
        assert status["phase"] == "reconnecting"
        assert status["last_error"] == "RuntimeError"
        assert "private-authenticated-url" not in json.dumps(status)
        assert backend._pending_input is None and backend._collecting is None
        assert backend._conversation._deadlines == {}
        await asyncio.sleep(0.03)
        assert scheduled == [True]
        await backend.close()

    asyncio.run(run())


def test_missing_model_reply_has_a_deadline(tmp_path, monkeypatch):
    from voice_agent.backends import live_speakers

    async def run():
        backend = make_backend(tmp_path)
        backend._ws = SimpleNamespace(closed=False)
        monkeypatch.setattr(live_speakers, "REPLY_TIMEOUT_SECONDS", 0.01, raising=False)

        async def start():
            pass

        async def send(message):
            pass

        monkeypatch.setattr(backend, "start_session", start)
        monkeypatch.setattr(backend, "_send", send)
        with pytest.raises(TimeoutError, match="Live reply timed out"):
            await asyncio.wait_for(backend._stream_input(SpeakerInput("7", "", "", 16000, ended=True)), 2)
        await backend.close()

    asyncio.run(run())


def test_late_keyword_audio_keeps_its_speaker_owned_first_audio_timing(tmp_path):
    from test_voice_reply_probability import fragment

    async def run():
        backend = make_backend(tmp_path)
        backend.settings.reply_probability_percent = 0
        backend.settings.force_reply_keywords = ["小欧"]
        turn = SpeakerInput("7", "", "", 16000)
        turn.submitted_at = time.monotonic() - 0.1
        backend._input = turn
        backend._input_started = turn.submitted_at
        backend.set_audio_out(lambda pcm, rate: None)
        await fragment(backend, b"reply", complete=True)
        assert backend._input_started is None
        await backend._handle_server_msg({"serverContent": {"inputTranscription": {"text": "小欧"}}})
        assert backend.speaker_status()["first_audio_ms"] >= 100
        await backend.close()

    asyncio.run(run())
