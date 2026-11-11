from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_gemini_session_lifecycle import FakeLiveWs

from voice_agent.backends import create_backend
from voice_agent.backends.live_speakers import SpeakerLiveBackend, resolve_speaker
from voice_agent.memory import MemoryStore
from voice_agent.settings import VoiceAgentSettings


def test_mapping_requires_matching_sender_and_current_membership():
    members = {"a": "Alice", "b": "Bob"}
    states = {"a": {"cid": 7, "sender_uid": "7"}, "b": {"cid": 8, "sender_uid": "8"}}
    assert resolve_speaker("7", states, members) == ("a", "Alice")
    assert resolve_speaker("7", states, {"b": "Bob"}) == ("", "")
    states["a"]["sender_uid"] = "9"
    assert resolve_speaker("7", states, members) == ("", "")
    states["a"]["sender_uid"] = "7"
    states["b"] = {"cid": 7, "sender_uid": "7"}
    assert resolve_speaker("7", states, members) == ("", "")


def make_backend(tmp_path):
    settings = VoiceAgentSettings(live_speaker_context=True, reply_probability_percent=100,
                                  voice_leave_enabled=False, voice_volume_enabled=False)
    memory = MemoryStore(str(tmp_path / "memory.jsonl"))
    backend = create_backend(settings, memory)
    assert isinstance(backend, SpeakerLiveBackend)
    return backend


def test_streams_speaker_metadata_and_pcm_before_sentence_end(tmp_path):
    async def run():
        backend = make_backend(tmp_path)
        sent = []
        backend._members = {"a": "Alice"}
        backend._states = lambda: {"a": {"cid": 7, "sender_uid": "7"}}
        backend._ws = SimpleNamespace(closed=False)

        async def start():
            pass

        async def send(message):
            sent.append(message)

        backend.start_session = start
        backend._send = send
        backend._ensure_input_worker()
        pcm = b"\x00\x20" * 640
        await backend.push_room_audio("7", pcm, 16000)
        for _ in range(15):
            await asyncio.sleep(0)
        assert sent[0] == {"realtimeInput": {"activityStart": {}}}
        first = sent[1]["realtimeInput"]
        assert '"oopz_uid": "a"' in first["text"]
        assert "Alice" in first["text"]
        assert base64.b64decode(first["audio"]["data"]) == pcm
        assert not any("activityEnd" in message["realtimeInput"] for message in sent)
        await backend.close()

    asyncio.run(run())


def test_allowed_audio_is_played_before_model_turn_completes(tmp_path):
    async def run():
        backend = make_backend(tmp_path)
        audio = []
        backend.set_audio_out(lambda pcm, rate: audio.append(pcm))
        await backend._handle_server_msg({"serverContent": {"modelTurn": {"parts": [{
            "inlineData": {"data": base64.b64encode(b"reply").decode(),
                           "mimeType": "audio/pcm;rate=24000"}}]}}})
        assert audio == [b"reply"]
        await backend.close()

    asyncio.run(run())


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.001)
    await asyncio.wait_for(wait(), 1)


def test_one_socket_separates_speakers_and_drains_late_transcription(tmp_path, monkeypatch):
    from voice_agent import ws_transport
    from voice_agent.backends import live_speakers

    async def run():
        sockets = []

        async def open_ws(*args, **kwargs):
            ws = FakeLiveWs()
            sockets.append(ws)
            return ws

        monkeypatch.setattr(ws_transport, "open_live_ws", open_ws)
        monkeypatch.setattr(live_speakers, "_LATE_TRANSCRIPTION_SECONDS", 0.03)
        backend = make_backend(tmp_path)
        backend.settings.gemini_api_key = "test"
        backend.settings.silence_ms = 500
        backend.settings.reply_probability_percent = 0
        backend.settings.force_reply_keywords = ["小欧"]
        backend._members = {"a": "Alice", "b": "Bob"}
        backend._states = lambda: {"a": {"cid": 7, "sender_uid": "7"},
                                   "b": {"cid": 8, "sender_uid": "8"}}
        backend._ensure_input_worker()
        a, b, silence = b"\x00\x20" * 1600, b"\x00\x30" * 1600, b"\x00\x00" * 1600
        try:
            await backend.push_room_audio("7", a, 16000)
            await until(lambda: sockets and len(sockets[0].sent) >= 3)
            setup = sockets[0].sent[0]["setup"]
            assert setup["realtime_input_config"]["automatic_activity_detection"]["disabled"]
            assert "oopz_uid" in setup["system_instruction"]["parts"][0]["text"]
            await backend.push_room_audio("8", b, 16000)
            for _ in range(5):
                await backend.push_room_audio("7", silence, 16000)
            await until(lambda: any(m.get("realtimeInput", {}).get("activityEnd") == {} for m in sockets[0].sent))
            await backend.push_room_audio("8", b, 16000)
            await backend._handle_server_msg({"serverContent": {"turnComplete": True}})
            await backend._handle_server_msg({"serverContent": {"inputTranscription": {"text": "小欧"}}})
            assert "b" not in backend._conversation._deadlines
            await until(lambda: sum("activityStart" in m.get("realtimeInput", {}) for m in sockets[0].sent) == 2)
            contexts = [m["realtimeInput"]["text"] for m in sockets[0].sent if "text" in m.get("realtimeInput", {})]
            assert '"oopz_uid": "a"' in contexts[0]
            assert '"oopz_uid": "b"' in contexts[1]
            assert len(sockets) == 1
        finally:
            await backend.close()
        assert backend._input_task is None and backend._pending_input is None

    asyncio.run(run())


def test_barge_in_stops_old_audio_once_and_preserves_new_speech(tmp_path):
    async def run():
        backend = make_backend(tmp_path)
        backend._members = {"a": "Alice", "b": "Bob"}
        backend._states = lambda: {"b": {"cid": 8, "sender_uid": "8"}}
        output, stops = [], []
        backend.set_audio_out(lambda pcm, rate: output.append(pcm))

        async def stop():
            stops.append(True)

        backend._barge_out = stop
        await backend._deliver_audio(b"\x00\x20" * 24000, 24000)
        speech = b"\x00\x30" * 1600
        for _ in range(4):
            await backend.push_room_audio("8", speech, 16000)
        await backend._deliver_audio(b"old-tail", 24000)
        assert stops == [True]
        assert len(output) == 1
        assert backend._pending_input.member == "b"
        assert b"".join(backend._pending_input.frames) == speech * 4
        await backend.close()

    asyncio.run(run())


def test_next_speaker_waits_for_scheduled_audio_when_barge_is_disabled(tmp_path, monkeypatch):
    async def run():
        backend = make_backend(tmp_path)
        backend.settings.barge_in = False
        sent = []
        backend._members = {"a": "Alice"}
        backend._states = lambda: {"a": {"cid": 7, "sender_uid": "7"}}

        async def stream(turn):
            sent.append(turn.member)

        monkeypatch.setattr(backend, "_stream_input", stream)
        await backend.push_room_audio("7", b"\x00\x20" * 640, 16000)
        backend._play_until = time.monotonic() + 0.15
        backend._ensure_input_worker()
        await asyncio.sleep(0.03)
        assert sent == []
        await until(lambda: bool(sent))
        await backend.close()

    asyncio.run(run())


def test_stale_input_does_not_reset_a_reconnected_socket(tmp_path, monkeypatch):
    async def run():
        backend = make_backend(tmp_path)
        backend._members = {"a": "Alice"}
        backend._states = lambda: {"a": {"cid": 7, "sender_uid": "7"}}
        backend._ws = SimpleNamespace(closed=False)
        sent, resets = [], []

        async def start():
            pass

        async def send(message):
            sent.append(message)

        async def reset():
            resets.append(True)

        monkeypatch.setattr(backend, "start_session", start)
        monkeypatch.setattr(backend, "_send", send)
        monkeypatch.setattr(backend, "_reset_session", reset)
        monkeypatch.setattr(backend, "_schedule_reconnect", lambda: None)
        backend._ensure_input_worker()
        pcm = b"\x00\x20" * 640
        await backend.push_room_audio("7", pcm, 16000)
        await until(lambda: len(sent) >= 2)
        backend._ws = SimpleNamespace(closed=False)
        await backend.push_room_audio("7", pcm, 16000)
        await until(lambda: backend._input is None)
        assert resets == []
        await backend.close()

    asyncio.run(run())


def test_real_member_objects_use_existing_name_resolver(tmp_path, monkeypatch):
    from oopz import name_resolver

    async def run():
        backend = make_backend(tmp_path)

        async def members(**kwargs):
            return SimpleNamespace(channel_members={"room": [SimpleNamespace(uid="a")]})

        async def names(uids):
            return {"a": "Alice"}

        monkeypatch.setattr(name_resolver, "get_resolver", lambda: SimpleNamespace(ensure_users=names))
        backend._room_bot = SimpleNamespace(channels=SimpleNamespace(get_voice_channel_members=members))
        backend._room_channel = "room"
        await backend._refresh_members()
        assert backend._members == {"a": "Alice"}
        await backend.close()

    asyncio.run(run())


def test_agent_rearms_output_after_barge_during_scheduled_tail(tmp_path, monkeypatch):
    from test_voice_session_regressions import make_agent

    async def run():
        async def enable(enabled):
            return {"ok": True}

        async def members(**kwargs):
            return {"channelMembers": {"room": [{"uid": "b", "name": "Bob"}]}}

        agent = make_agent(tmp_path, live_speaker_context=True, barge_in_hold_ms=0)
        agent._channel = "room"
        source = SimpleNamespace(enable_speaker_turns=enable,
            voice_states=lambda: {"b": {"cid": 8, "sender_uid": "8"}})
        agent.duplex.transport = source
        agent._bot = SimpleNamespace(channels=SimpleNamespace(get_voice_channel_members=members))
        backend = agent.backend
        sent = []

        async def start():
            pass

        async def send(message):
            sent.append(message)

        monkeypatch.setattr(backend, "start_session", start)
        monkeypatch.setattr(backend, "_send", send)
        try:
            await agent._wire_live()
            await backend._deliver_audio(b"\x00\x20" * 24000, 24000)
            await backend._handle_server_msg({"serverContent": {"turnComplete": True}})
            await agent._on_remote_pcm("8", b"\x00\x30" * 640, 16000)
            assert agent._discard_live_audio
            await until(lambda: len(sent) >= 2)
            assert not agent._discard_live_audio
            await backend._deliver_audio(b"new-reply", 24000)
            assert agent.duplex.audio == [b"new-reply"]
        finally:
            await backend.close()

    asyncio.run(run())


def test_enabling_speaker_mode_restarts_existing_room_captures(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the browser capture fixture")
    source = (Path(__file__).resolve().parents[1] /
              "src/oopz_sdk/assets/voice/agora_player.html").read_text(encoding="utf-8")
    function = source[source.index("window.agoraSetSpeakerTurns ="):source.index("const remoteCaptures =")]
    script = """
const assert = require('node:assert/strict');
const window = {};
let speakerTurnMode = false, listenEnabled = true;
const client = {};
let captureSamples = 4096, stops = 0;
function stopAllRemoteCaptures() { captureSamples = 0; stops++; }
window.agoraSetListen = async () => { captureSamples = speakerTurnMode ? 1024 : 4096; return {ok:true}; };
""" + function + """
(async () => {
  assert((await window.agoraSetSpeakerTurns(true)).ok);
  assert.equal(captureSamples, 1024);
  await window.agoraSetSpeakerTurns(true);
  assert.equal(stops, 1);
  await window.agoraSetSpeakerTurns(false);
  assert.equal(captureSamples, 4096);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    path = tmp_path / "speaker_mode.cjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([node, str(path)], capture_output=True, text=True,
                            encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr


def test_session_reset_allows_announcements_after_previous_barge(tmp_path):
    async def run():
        backend = make_backend(tmp_path)
        played = []
        backend.set_audio_out(lambda pcm, rate: played.append(pcm))
        backend._barged = True
        await backend._reset_session()
        await backend._deliver_audio(b"announcement", 24000)
        assert played == [b"announcement"]
        await backend.close()

    asyncio.run(run())


def test_close_rejects_audio_arriving_during_browser_cleanup(tmp_path):
    async def run():
        backend = make_backend(tmp_path)

        async def disable(enabled):
            await backend.push_room_audio("7", b"\x00\x20" * 640, 16000)
            return {"ok": True}

        backend._room_transport = SimpleNamespace(enable_speaker_turns=disable)
        await backend.close()
        assert backend._pending_input is None and backend._collecting is None

    asyncio.run(run())
