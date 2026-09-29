"""voice_agent 冒烟测试：不依赖网络与 Oopz。"""

from __future__ import annotations

import os
import struct
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from voice_agent.memory import MemoryStore  # noqa: E402
from voice_agent.settings import load_voice_agent_settings  # noqa: E402
from voice_agent.vad import EnergyVad, VadvConfig  # noqa: E402
from voice_agent.backends.mimo_cascade import pcm16_to_wav, resample_pcm16, wav_to_pcm16  # noqa: E402


def test_settings_defaults() -> None:
    agent, api = load_voice_agent_settings()
    assert agent.backend in {"mimo_cascade", "gemini_live", "openai_realtime", ""} or agent.backend
    assert api.port == 3091 or api.port > 0
    print("settings ok", agent.backend, api.port)


def test_memory() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "m.jsonl")
        store = MemoryStore(path, max_turns=5)
        store.set_persona("测试人格")
        store.append("user", "你好", user_key="qq:1")
        store.append("assistant", "你好呀", user_key="qq:1")
        msgs = store.as_messages(user_key="qq:1")
        assert msgs[-1]["content"] == "你好呀"
        assert store.get_persona() == "测试人格"
        assert store.clear(user_key="qq:1") == 2
    print("memory ok")


def test_vad_silence_and_speech() -> None:
    vad = EnergyVad(VadvConfig(sample_rate=16000, silence_ms=120, energy_threshold=0.02))
    # 500ms 静音
    silence = struct.pack("<" + "h" * 800, *([0] * 800))
    assert vad.feed(silence) is None
    # 说话 200ms + 静音 200ms -> 一句
    loud = struct.pack("<" + "h" * 3200, *([8000] * 3200))
    tail = struct.pack("<" + "h" * 3200, *([0] * 3200))
    assert vad.feed(loud) is None
    utt = vad.feed(tail)
    assert utt is not None and len(utt) > 0
    print("vad ok", len(utt or b""))


def test_wav_roundtrip_and_resample() -> None:
    pcm = struct.pack("<" + "h" * 1600, *([1000] * 1600))
    wav = pcm16_to_wav(pcm, 16000)
    back, rate = wav_to_pcm16(wav)
    assert rate == 16000 and back == pcm
    up = resample_pcm16(pcm, 16000, 24000)
    assert len(up) > len(pcm)
    print("wav/resample ok", len(up))


if __name__ == "__main__":
    test_settings_defaults()
    test_memory()
    test_vad_silence_and_speech()
    test_wav_roundtrip_and_resample()
    print("ALL SMOKE TESTS PASSED")
