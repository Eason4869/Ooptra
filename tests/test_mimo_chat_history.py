"""级联的当前问题只应发送一次，记忆仍保存当前回合。"""

from __future__ import annotations

import asyncio

from voice_agent.backends.mimo_cascade import MimoCascadeBackend
from voice_agent.memory import MemoryStore
from voice_agent.settings import VoiceAgentSettings


def test_current_question_is_not_duplicated_in_chat_request(monkeypatch, tmp_path):
    captured = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def json(self, **kwargs):
            return {"choices": [{"message": {"content": "answer"}}]}

    class Session:
        def post(self, url, **kwargs):
            captured.extend(kwargs["json"]["messages"])
            return Response()

    async def run():
        memory = MemoryStore(str(tmp_path / "memory.jsonl"))
        memory.append("user", "previous", user_key="oopz:u")
        memory.append("assistant", "previous reply", user_key="oopz:u")
        backend = MimoCascadeBackend(VoiceAgentSettings(mimo_api_key="test"), memory)

        async def asr(*args):
            return "current question"

        async def tts(*args):
            return b"", 24000

        async def http():
            return Session()

        monkeypatch.setattr(backend, "asr", asr)
        monkeypatch.setattr(backend, "tts", tts)
        monkeypatch.setattr(backend, "_http", http)
        await backend.handle_utterance(b"\x01\x00" * 320, sample_rate=16000, user_key="oopz:u")
        assert [m["content"] for m in captured if m["role"] == "user"] == [
            "previous", "current question",
        ]
        assert [m["content"] for m in memory.as_messages(user_key="oopz:u")] == [
            "previous", "previous reply", "current question", "answer",
        ]

    asyncio.run(run())
