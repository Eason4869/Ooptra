"""Live 模式「回合生命周期」：``_speaking`` 由回合边界驱动，打断边沿触发。

这个文件存在的理由（B4）：``_wire_live.on_audio`` 在每个音频分片上把
``_speaking = True``，而修复前 Live 模式下**除了 leave() 没有任何地方把它置回
False** —— 于是 ``_on_remote_pcm`` 的 barge-in 分支在**每个远端音频帧**
（20ms 一帧、房间里每个人）上各执行一次 ``interrupt()`` + ``stop_tts()``：

  * 一次 4.4 秒的回复实测 13 个分片 → 13 次掐断，语音被剁成 ~340ms 碎片，
    碎片之间夹 30ms 静音（听感 =「能听见但听不清」）
  * 每个分片都发 ``audioStreamEnd`` 告诉模型「输入流结束」→ 换频道后彻底不说话
  * 每个分片都在 CDP 热路径上再加一次 30ms 等待 → 会话每 24~27 秒自持抖动断连

现在：``turnComplete`` / ``interrupted`` 这两个**真实的回合边界**通过
``set_turn_out`` 外泄给编排层，打断由 ``_barge_in_armed`` 边沿闸门限制为
「一次出声最多打断一次」。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from voice_agent.agent import VoiceAgent
from voice_agent.backends.gemini_live import LANGUAGE_GUARD, GeminiLiveBackend
from voice_agent.settings import VoiceAgentSettings, load_voice_agent_settings
from voice_agent.ws_transport import _AiohttpWs

# 16k / mono / 16bit 的 20ms 远端音频帧
FRAME = b"\x00\x01" * 320
#: 一次 4.4 秒的回复实测约 13 个音频分片
CHUNKS = 13


# ----------------------------------------------------------------------
# 假 duplex / 假后端：驱动真的 VoiceAgent，不碰网络与浏览器
# ----------------------------------------------------------------------


class FakeDuplex:
    def __init__(self) -> None:
        self.tts_chunks = 0
        self.stop_calls = 0

    def set_remote_pcm_handler(self, handler: Any) -> None:
        self._handler = handler

    async def start(self) -> None:
        pass

    async def enable_listen(self, on: bool = True) -> dict:
        return {"ok": True}

    async def push_tts_pcm(self, pcm: bytes, rate: int, *, finish: bool = False) -> dict:
        self.tts_chunks += 1
        return {"ok": True}

    async def stop_tts(self) -> dict:
        self.stop_calls += 1
        return {"ok": True}

    async def close(self) -> None:
        pass


class FakeBackend:
    """只统计调用次数；``session_active`` 恒真。"""

    def __init__(self) -> None:
        self.interrupt_calls = 0
        self.pushed_frames = 0
        self.spoken: list[str] = []
        self.session_active = True
        self._audio_out: Any = None
        self._turn_out: Any = None

    def set_audio_out(self, handler: Any) -> None:
        self._audio_out = handler

    def set_text_out(self, handler: Any) -> None:
        pass

    def set_turn_out(self, handler: Any) -> None:
        self._turn_out = handler

    async def interrupt(self) -> None:
        self.interrupt_calls += 1

    async def push_audio(self, pcm: bytes, rate: int | None = None) -> None:
        self.pushed_frames += 1

    async def speak_text(self, text: str) -> None:
        self.spoken.append(text)

    async def start_session(self) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def emit_audio(self, n: int = 1) -> None:
        """模型吐音频分片 —— 会走 on_audio。"""
        for _ in range(n):
            await self._audio_out(b"\x01\x02" * 480, 24000)

    async def end_turn(self, interrupted: bool = False) -> None:
        """服务端推 ``turnComplete`` / ``interrupted`` —— 唯一的回合边界。"""
        assert self._turn_out is not None, "_wire_live 没有注册 turn 回调"
        await self._turn_out(interrupted)


class _StubVad:
    """级联路径用：永不切句，只测打断分支。"""

    def feed(self, pcm: bytes) -> None:
        return None

    def reset(self) -> None:
        pass


def _make_agent(*, live: bool = True) -> tuple[VoiceAgent, FakeDuplex, FakeBackend]:
    agent = VoiceAgent.__new__(VoiceAgent)
    agent.settings = load_voice_agent_settings()[0]
    # 这三项必须显式写死：CI 的 config.py 由 config.example.py 生成，其中
    # VOICE_AGENT_CONFIG.enabled 为 False —— 那样 _on_remote_pcm 会在第一道门
    # 就 return，断言「0 次打断」的用例会假通过，断言「1 次」的则直接挂。
    agent.settings.enabled = True
    agent.settings.backend = "gemini_live" if live else "mimo_cascade"
    agent.settings.barge_in = True
    agent.settings.listen_only_uids = []
    agent._bot = None
    agent._joined = True
    agent._speaking = False
    agent._barge_in_armed = True
    agent._user_buffers = {"u1": _StubVad()}
    agent._vad = None
    agent._task = None
    agent.memory = type(
        "M", (), {"append": lambda *a, **k: None, "set_persona": lambda *a: None}
    )()
    agent.last_reply = ""
    agent.last_user_text = ""
    agent.turns = 0
    agent._area = "area1"
    agent._channel = "chan1"
    agent._utterance_tasks = set()

    duplex, backend = FakeDuplex(), FakeBackend()
    agent.duplex = duplex
    agent.backend = backend
    agent.live_mode = live
    return agent, duplex, backend


async def _wire(agent: VoiceAgent) -> None:
    await agent._wire_live()


# ----------------------------------------------------------------------
# 1~5：Live 回合生命周期
# ----------------------------------------------------------------------


def test_interleaved_chunks_trigger_barge_in_once() -> None:
    """核心回归：分片与音频帧交替时，一次出声只打断一次（原来每分片一次）。"""

    async def run() -> None:
        agent, duplex, backend = _make_agent()
        await _wire(agent)

        for _ in range(CHUNKS):
            await backend.emit_audio(1)  # 模型吐一个分片
            await agent._on_remote_pcm("u1", FRAME, 16000)  # 20ms 后用户来一帧

        assert backend.pushed_frames == CHUNKS, "音频帧没有进入 Live 会话，本例不作数"
        assert backend.interrupt_calls == 1, f"打断被触发了 {backend.interrupt_calls} 次"
        assert duplex.stop_calls == 1, f"播放队列被清空 {duplex.stop_calls} 次"

    asyncio.run(run())


def test_speaking_is_false_right_after_model_finished() -> None:
    """模型说完后用户才开口：不该被当成抢话。"""

    async def run() -> None:
        agent, duplex, backend = _make_agent()
        await _wire(agent)

        await backend.emit_audio(5)
        await backend.end_turn(False)  # turnComplete
        assert agent._speaking is False, "回合结束后 _speaking 没有回落"

        for _ in range(50):
            await agent._on_remote_pcm("u1", FRAME, 16000)

        # 先确认这 50 帧真的走到了 push_audio：否则「0 次打断」可能只是因为
        # 帧在入口就被丢弃（enabled/listen_only_uids），断言等于空转。
        assert backend.pushed_frames == 50, "音频帧没有进入 Live 会话，本例不作数"
        assert backend.interrupt_calls == 0
        assert duplex.stop_calls == 0

    asyncio.run(run())


def test_turns_increments_once_per_reply() -> None:
    """一轮回复吐 N 个分片，只记 1 轮（原来每个分片 +1，一轮记成十几轮）。"""

    async def run() -> None:
        agent, _duplex, backend = _make_agent()
        await _wire(agent)

        await backend.emit_audio(CHUNKS)
        assert agent.turns == 0, "分片到达就自增了轮次（回合边界才是唯一计数点）"

        await backend.end_turn(False)
        assert agent.turns == 1

    asyncio.run(run())


def test_live_speak_text_counts_the_turn_at_the_boundary() -> None:
    """``/voice/speak`` 在 Live 模式下不自己计轮次，交给回合边界 —— 否则一次说
    一句话会被记成两轮（API 刚 +1，模型说完的 ``turnComplete`` 再 +1）。"""

    async def run() -> None:
        agent, _duplex, backend = _make_agent()
        await _wire(agent)

        result = await agent.speak_text("你好")
        assert result["mode"] == "live"
        assert backend.spoken == ["你好"]
        assert agent.turns == 0, "speak_text 自己计了轮次，回合边界会再计一次"

        await backend.end_turn(False)  # 模型说完了
        assert agent.turns == 1

    asyncio.run(run())


def test_barge_in_rearms_for_the_next_turn() -> None:
    """下一回合重新武装：新的一次出声仍能被抢话打断一次。"""

    async def run() -> None:
        agent, _duplex, backend = _make_agent()
        await _wire(agent)

        await backend.emit_audio(1)
        await agent._on_remote_pcm("u1", FRAME, 16000)
        assert backend.interrupt_calls == 1
        await backend.end_turn(True)

        await backend.emit_audio(1)
        await agent._on_remote_pcm("u1", FRAME, 16000)
        assert backend.interrupt_calls == 2, "第二回合没能再打断（闸门没有重新武装）"

    asyncio.run(run())


def test_server_side_interrupted_clears_local_playback() -> None:
    """服务端自己判定抢话（``interrupted``）时，本地已排期的分片要就地丢掉。

    否则模型已经停口，喇叭还在把缓冲播完 ——「模型不说了、喇叭还在说」。
    """

    async def run() -> None:
        agent, duplex, backend = _make_agent()
        await _wire(agent)

        await backend.emit_audio(3)
        assert duplex.stop_calls == 0
        await backend.end_turn(True)  # 服务端：用户抢话了

        assert duplex.stop_calls == 1, "被抢话时没有清掉本地播放队列"
        assert agent._speaking is False

    asyncio.run(run())


# ----------------------------------------------------------------------
# 6：级联模式行为不变（回归锁）
# ----------------------------------------------------------------------


def test_cascade_barge_in_unchanged() -> None:
    """级联模式仍走 ``_interrupt_speaking``，一次打断只清一次播放队列。"""

    async def run() -> None:
        agent, duplex, _backend = _make_agent(live=False)
        await _wire(agent)

        agent._speaking = True
        await agent._on_remote_pcm("u1", FRAME, 16000)
        assert duplex.stop_calls == 1
        assert agent._speaking is False

        # 已经落回 False，后续帧不再重复清队列
        for _ in range(10):
            await agent._on_remote_pcm("u1", FRAME, 16000)
        assert duplex.stop_calls == 1

    asyncio.run(run())


# ----------------------------------------------------------------------
# 7：start_session 可重入（热路径上的重建风暴）
# ----------------------------------------------------------------------


class FakeLiveWs:
    """够用的假 Live socket：收到 setup 就回 setupComplete。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def send(self, raw: str) -> None:
        if self.closed:
            raise RuntimeError("Cannot write to closing transport")
        msg = json.loads(raw)
        self.sent.append(msg)
        if "setup" in msg:
            await self._queue.put(json.dumps({"setupComplete": {}}))

    def __aiter__(self) -> FakeLiveWs:
        return self

    async def __anext__(self) -> str:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def close(self) -> None:
        self.closed = True
        await self._queue.put(None)


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[FakeLiveWs]:
    created: list[FakeLiveWs] = []

    async def fake_open(url: str, *, proxy: str | None = None, **kwargs: Any) -> FakeLiveWs:
        # 这个 await 是**用例有效性**的前提：没有它，start_session 的临界区里
        # 一个真正的挂起点都没有，5 个协程会被逐个同步跑完，锁与复检根本没被走到 ——
        # 修锁之前这个用例也是绿的（空转）。见 test_concurrent_start_session_connects_once。
        await asyncio.sleep(0)
        ws = FakeLiveWs()
        created.append(ws)
        return ws

    import voice_agent.ws_transport as transport

    monkeypatch.setattr(transport, "open_live_ws", fake_open)
    return created


def _backend(persona: str = "测试") -> GeminiLiveBackend:
    return GeminiLiveBackend(
        VoiceAgentSettings(
            enabled=True,
            gemini_api_key="test-key",
            gemini_model="gemini-test",
            persona=persona,
            proxy="",
        ),
        type("M", (), {"append": lambda *a, **k: None, "set_persona": lambda *a: None})(),
    )


def test_concurrent_start_session_connects_once(opened: list[FakeLiveWs]) -> None:
    """并发 start_session（push_audio 在热路径上也会调）只真正建连一次。"""

    async def run() -> None:
        backend = _backend()
        await asyncio.gather(*(backend.start_session() for _ in range(5)))
        assert len(opened) == 1, f"并发建连了 {len(opened)} 次会话"
        assert backend.session_active is True
        await backend.aclose()

    asyncio.run(run())


# ----------------------------------------------------------------------
# 9：抢话不再向服务端发 audioStreamEnd
# ----------------------------------------------------------------------


def test_interrupt_sends_no_server_signal(opened: list[FakeLiveWs]) -> None:
    """``audioStreamEnd`` 的语义是「用户说完了，立刻回答」，拿它抢话说反了。

    它会让模型把缓冲里的音频**碎片**当成一个完整回合去回答 —— 一整段没有内容的
    输入，模型只能瞎猜（语言乱切换就是从这里开始的）。抢话由服务端自动 VAD 判定，
    客户端只需要停掉本地播放。
    """

    async def run() -> None:
        backend = _backend()
        await backend.start_session()
        ws = opened[0]

        await backend.interrupt()

        assert not [
            m for m in ws.sent if "audioStreamEnd" in json.dumps(m)
        ], "抢话又向服务端发了 audioStreamEnd"
        assert backend.session_active is True, "interrupt 不该把会话搞掉"
        await backend.aclose()

    asyncio.run(run())


# ----------------------------------------------------------------------
# 10：语言约束必须跟着人格一起下发
# ----------------------------------------------------------------------


def test_setup_appends_the_language_guard(opened: list[FakeLiveWs]) -> None:
    """Live 原生音频模型不支持 speech_config.language_code 锁语言，只能靠提示词。"""

    async def run() -> None:
        backend = _backend("用中文回答。你是测试人格。")
        await backend.start_session()
        text = opened[0].sent[0]["setup"]["system_instruction"]["parts"][0]["text"]

        assert "用中文回答。你是测试人格。" in text, "人格本身不能被吞掉"
        assert LANGUAGE_GUARD in text, "语言约束没有下发"
        assert text.index(LANGUAGE_GUARD) > text.index("测试人格"), (
            "语言约束必须追加在人格之后（收尾位置权重更高）"
        )
        await backend.aclose()

    asyncio.run(run())


def test_language_guard_survives_an_empty_persona(opened: list[FakeLiveWs]) -> None:
    """人格是用户可清空的配置项；清空后语言约束仍要在。"""

    async def run() -> None:
        backend = _backend("")
        await backend.start_session()
        text = opened[0].sent[0]["setup"]["system_instruction"]["parts"][0]["text"]
        assert LANGUAGE_GUARD in text
        await backend.aclose()

    asyncio.run(run())


# ----------------------------------------------------------------------
# 8：断线原因不再被吞掉
# ----------------------------------------------------------------------


class _FakeMsg:
    def __init__(self, type_: Any, data: Any = "") -> None:
        self.type = type_
        self.data = data


class _FakeAiohttpWs:
    def __init__(self, msgs: list[_FakeMsg]) -> None:
        self._msgs = msgs
        self.close_code = 1000

    def __aiter__(self) -> Any:
        return self._iter()

    async def _iter(self) -> Any:
        for msg in self._msgs:
            yield msg

    def exception(self) -> Exception:
        return RuntimeError("connection reset by peer")

    async def close(self) -> None:
        pass


def test_aiohttp_close_logs_reason(caplog: pytest.LogCaptureFixture) -> None:
    """CLOSE 时既要把已收到的数据放出去，也要留下 close_code 与异常。"""

    async def run() -> None:
        import aiohttp

        inner = _FakeAiohttpWs(
            [
                _FakeMsg(aiohttp.WSMsgType.TEXT, "hello"),
                _FakeMsg(aiohttp.WSMsgType.CLOSE, "server said bye"),
            ]
        )
        adapted = _AiohttpWs(inner, None)
        with caplog.at_level("INFO", logger="voice_agent.ws_transport"):
            got = [chunk async for chunk in adapted]

        assert got == ["hello"], "关闭前收到的数据不能丢"
        assert "close_code=1000" in caplog.text, "断线日志里没有 close_code"
        assert "connection reset by peer" in caplog.text, "断线日志里没有底层异常"

    asyncio.run(run())
