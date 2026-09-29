"""语音对话编排。

Live 模式（默认，gemini_live）：远端 PCM 持续灌入 Live 会话，模型音频直接推回，
不做「切句 → ASR → LLM → TTS」。

级联模式（mimo_cascade）：VAD 断句后走 ASR/LLM/TTS，作为兜底。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from voice_agent.backends import create_backend
from voice_agent.duplex import VoiceDuplex
from voice_agent.memory import MemoryStore
from voice_agent.settings import VoiceAgentSettings, VoiceApiSettings
from voice_agent.vad import EnergyVad, VadvConfig

logger = logging.getLogger(__name__)


def _is_live_backend(backend: Any) -> bool:
    return bool(getattr(backend, "session_active", None) is not None or
                getattr(backend, "name", "") in {"gemini_live", "openai_realtime"} or
                hasattr(backend, "push_audio"))


# 改了这些字段就必须重建记忆 / VAD / 已建立的模型会话，否则旧值继续生效
_MEMORY_FIELDS = {"memory_path", "memory_max_turns"}
_VAD_FIELDS = {"sample_rate_in", "silence_ms", "max_utterance_ms"}
_SESSION_FIELDS = {
    "persona",
    "proxy",
    "gemini_api_key",
    "gemini_base_url",
    "gemini_model",
    "gemini_voice",
    "openai_api_key",
    "openai_base_url",
    "openai_realtime_model",
    "openai_voice",
    "mimo_api_key",
    "mimo_base_url",
    "mimo_asr_model",
    "mimo_llm_model",
    "mimo_tts_model",
    "mimo_tts_voice",
}


class VoiceAgent:
    def __init__(
        self,
        settings: VoiceAgentSettings,
        api_settings: VoiceApiSettings,
        *,
        bot: Any = None,
    ) -> None:
        self.settings = settings
        self.api_settings = api_settings
        self._bot = bot
        self.memory = MemoryStore(settings.memory_path, settings.memory_max_turns)
        self.memory.set_persona(settings.persona)
        self.backend = create_backend(settings, self.memory)
        self.live_mode = _is_live_backend(self.backend)
        self.duplex: VoiceDuplex | None = None
        self._vad = self._make_vad()
        self._user_buffers: dict[str, EnergyVad] = {}
        self._task: asyncio.Task | None = None
        self._busy = asyncio.Lock()
        self._speaking = False
        # Live 模式的抢话闸门：一次「模型出声」最多只打断一次。见 _on_remote_pcm。
        self._barge_in_armed = True
        self._joined = False
        self._area = settings.area
        self._channel = settings.channel
        self.last_reply = ""
        self.last_user_text = ""
        self.turns = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        task = self._task
        return task is not None and not task.done()

    def bind_bot(self, bot: Any) -> None:
        self._bot = bot

    def bind_duplex(self, duplex: VoiceDuplex) -> None:
        self.duplex = duplex
        duplex.set_remote_pcm_handler(self._on_remote_pcm)

    async def start(self) -> None:
        if not self.settings.enabled:
            logger.info("voice agent disabled")
            return
        self.memory.set_persona(self.settings.persona)
        if self.duplex is not None:
            await self.duplex.start()
            await self.duplex.enable_listen(True)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop(), name="voice-agent-loop")
        if self.settings.auto_join and self._bot is not None:
            try:
                await self.join(self._area, self._channel)
            except Exception:
                logger.exception("auto join voice channel failed")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        try:
            await self.leave()
        except Exception:
            logger.debug("leave on stop failed", exc_info=True)
        if self.duplex is not None:
            await self.duplex.close()
        await self.backend.aclose()

    async def _run_loop(self) -> None:
        """会话保活：已进房但 Live 会话掉了就自动重连。

        Live 会话可能因为代理抖动/长时间空闲被服务端关掉；没有这个监督时，
        agent 会一直以为自己还在说话，实际音频早已进黑洞。
        """
        while True:
            await asyncio.sleep(15)
            if not (self._joined and self.live_mode):
                continue
            backend = self.backend
            active = getattr(backend, "session_active", None)
            if active is None or active:
                continue
            start = getattr(backend, "start_session", None)
            if start is None:
                continue
            logger.warning("Live 会话已断开，正在重连…")
            try:
                await start()
            except Exception as exc:
                logger.warning("语音会话重连失败：%s", exc)

    def _make_vad(self) -> EnergyVad:
        return EnergyVad(
            VadvConfig(
                sample_rate=self.settings.sample_rate_in,
                silence_ms=self.settings.silence_ms,
                max_utterance_ms=self.settings.max_utterance_ms,
            )
        )

    async def refresh(self, changed: list[str]) -> list[str]:
        """配置就地更新后，把派生对象与会话同步到新值。

        返回给用户看的提示（哪些东西被重建了）。``changed`` 是字段名列表。
        """
        if not changed:
            return []
        changed_set = set(changed)
        notes: list[str] = []

        if _MEMORY_FIELDS & changed_set:
            self.memory = MemoryStore(self.settings.memory_path, self.settings.memory_max_turns)
            self.memory.set_persona(self.settings.persona)
            self.backend.memory = self.memory
            notes.append("记忆存储已重建")

        if _VAD_FIELDS & changed_set:
            self._vad = self._make_vad()
            self._user_buffers.clear()
            notes.append("断句参数已重建")

        if "persona" in changed_set:
            self.memory.set_persona(self.settings.persona)

        if "backend" in changed_set:
            await self.backend.aclose()
            self.backend = create_backend(self.settings, self.memory)
            self.live_mode = _is_live_backend(self.backend)
            notes.append("语音后端已切换")

        session_dirty = bool(_SESSION_FIELDS & changed_set) or "backend" in changed_set
        if not session_dirty:
            return notes

        if not (self._joined and self.live_mode):
            # 没进房时无需重建会话，下次 join 自然用新配置
            return notes
        start = getattr(self.backend, "start_session", None)
        if start is None:
            return notes
        await self._wire_live()
        try:
            await start()
        except Exception as exc:
            logger.warning("按新配置重建语音会话失败：%s", exc)
            return [*notes, f"语音会话重建失败：{exc}"]
        notes.append("语音会话已按新配置重建")
        return notes

    # ------------------------------------------------------------------
    # 进退房
    # ------------------------------------------------------------------

    def _resolve_target(self, area: str, channel: str) -> tuple[str, str]:
        area = (area or self._area or "").strip()
        channel = (channel or self._channel or "").strip()
        if not area or not channel:
            try:
                import config as runtime_config

                area = area or str(runtime_config.OOPZ_CONFIG.get("default_area") or "")
                channel = channel or str(runtime_config.OOPZ_CONFIG.get("default_channel") or "")
            except Exception:
                pass
        return area, channel

    async def join(self, area: str = "", channel: str = "") -> dict[str, Any]:
        if self._bot is None:
            raise RuntimeError("Oopz bot 尚未就绪")
        area, channel = self._resolve_target(area, channel)
        if not area or not channel:
            raise RuntimeError("缺少 area/channel，请在配置或调用参数中指定")
        if self.duplex is None:
            voice = getattr(self._bot, "voice", None)
            if voice is None:
                raise RuntimeError("bot.voice 不存在")
            self.bind_duplex(VoiceDuplex(voice.backend))
            await self.duplex.start()
            await self.duplex.enable_listen(True)

        sign = await self._bot.voice.join(area=area, channel=channel)
        self._area = area
        self._channel = channel
        self._joined = True
        self._speaking = False
        self._barge_in_armed = True
        await self.duplex.enable_listen(True)

        # Live：建立双向语音会话，并把模型出声接到推流
        if self.live_mode:
            await self._wire_live()
            start = getattr(self.backend, "start_session", None)
            if start is not None:
                await start()

        payload = {
            "ok": True,
            "area": area,
            "channel": channel,
            "rtc_channel": getattr(sign, "rtc_channel_name", ""),
            "mode": "live" if self.live_mode else "cascade",
        }
        logger.info("voice agent joined %s/%s mode=%s", area, channel, payload["mode"])
        return payload

    async def _wire_live(self) -> None:
        duplex = self.duplex
        if duplex is None:
            return

        async def on_audio(pcm: bytes, rate: int) -> None:
            # 收到分片只说明「这一回合正在出声」，**不代表回合结束**：
            # 以前在这里 turns += 1，一次回复实测 13 个分片就虚增 13 轮；
            # 而 _speaking 置 True 后没有任何地方回落，导致下面 _on_remote_pcm
            # 的抢话分支被每个分片各触发一次。回合边界一律由 on_turn_end 负责。
            self._speaking = True
            await duplex.push_tts_pcm(pcm, rate, finish=False)

        async def on_text(text: str) -> None:
            self.last_reply = text

        async def on_turn_end(interrupted: bool) -> None:
            """一个回合结束（说完了，或被抢话打断）。"""
            self._speaking = False
            self.turns += 1
            # 下一回合允许再打断一次
            self._barge_in_armed = True
            if interrupted and self.duplex is not None:
                # 服务端自己判定用户抢话：模型已经停口，但本地排期的分片还在播，
                # 必须就地清掉，否则「模型不说了、喇叭还在说」直到缓冲播完。
                with contextlib.suppress(Exception):
                    await self.duplex.stop_tts()

        setter_audio = getattr(self.backend, "set_audio_out", None)
        if setter_audio:
            setter_audio(on_audio)
        setter_text = getattr(self.backend, "set_text_out", None)
        if setter_text:
            setter_text(on_text)
        setter_turn = getattr(self.backend, "set_turn_out", None)
        if setter_turn:
            setter_turn(on_turn_end)

    async def leave(self) -> dict[str, Any]:
        if self._bot is not None and self._joined:
            try:
                await self._bot.voice.leave()
            except Exception:
                logger.debug("voice.leave failed", exc_info=True)
        # 退房就关掉 Live 会话：否则 Gemini 会话会一直挂着（既计费又占并发），
        # 而且下次进房时 start_session 会因为旧会话状态而变成空操作。
        aclose = getattr(self.backend, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                logger.debug("backend close on leave failed", exc_info=True)
        self._joined = False
        self._speaking = False
        self._barge_in_armed = True
        self._user_buffers.clear()
        self._vad.reset()
        return {"ok": True}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.enabled,
            "backend": self.settings.backend,
            "mode": "live" if self.live_mode else "cascade",
            "joined": self._joined,
            "area": self._area,
            "channel": self._channel,
            "speaking": self._speaking,
            "turns": self.turns,
            "last_user_text": self.last_user_text,
            "last_reply": self.last_reply,
            "persona_len": len(self.settings.persona),
        }

    # ------------------------------------------------------------------
    # 音频进出
    # ------------------------------------------------------------------

    def _vad_for(self, uid: str) -> EnergyVad:
        vad = self._user_buffers.get(uid)
        if vad is None:
            vad = EnergyVad(
                VadvConfig(
                    sample_rate=self.settings.sample_rate_in,
                    silence_ms=self.settings.silence_ms,
                    max_utterance_ms=self.settings.max_utterance_ms,
                )
            )
            self._user_buffers[uid] = vad
        return vad

    async def _on_remote_pcm(self, uid: str, pcm: bytes, sample_rate: int) -> None:
        if not self.settings.enabled or not pcm:
            return
        uid = str(uid or "unknown")
        if self.settings.listen_only_uids and uid not in self.settings.listen_only_uids:
            return

        if self.live_mode:
            # Live：持续灌入，模型自己做打断/回合。
            # 抢话必须**边沿触发**：这是每个远端音频帧（20ms 一帧、房间里每个人）
            # 都会走的路径。若按电平判定，模型每吐一个分片就会把 _speaking 顶回
            # True，紧接着下一帧就把刚排好的播放队列整个清掉 —— 一次 4.4 秒的回复
            # 被剁成 13 段碎片并夹 13 次 30ms 静音，听感就是「能听见但听不清」。
            # 闸门保证一次出声只打断一次，直到该回合结束才重新武装。
            if self.settings.barge_in and self._speaking and self._barge_in_armed:
                self._barge_in_armed = False
                interrupt = getattr(self.backend, "interrupt", None)
                if interrupt is not None:
                    await interrupt()
                if self.duplex is not None:
                    with contextlib.suppress(Exception):
                        await self.duplex.stop_tts()
                self._speaking = False
            push = getattr(self.backend, "push_audio", None)
            if push is not None:
                await push(pcm, sample_rate)
            return

        # 级联：VAD 切句
        if self._speaking and self.settings.barge_in:
            await self._interrupt_speaking()
        vad = self._vad_for(uid)
        utterance = vad.feed(pcm)
        if utterance:
            self._utterance_tasks = getattr(self, "_utterance_tasks", set())
            task = asyncio.create_task(self._handle_utterance(uid, utterance, sample_rate))
            self._utterance_tasks.add(task)
            task.add_done_callback(self._utterance_tasks.discard)

    async def _interrupt_speaking(self) -> None:
        self._speaking = False
        if self.duplex is not None:
            try:
                await self.duplex.stop_tts()
            except Exception:
                logger.debug("stop tts on barge-in failed", exc_info=True)

    async def _handle_utterance(self, uid: str, pcm: bytes, sample_rate: int) -> None:
        if not pcm:
            return
        async with self._busy:
            try:
                reply = await self.backend.handle_utterance(
                    pcm,
                    sample_rate=sample_rate,
                    user_key=f"oopz:{uid}",
                    channel_key=f"{self._area}/{self._channel}",
                )
            except Exception as exc:
                logger.exception("voice backend failed")
                self.last_reply = f"[error] {exc}"
                return

            self.last_user_text = reply.user_text or self.last_user_text
            if reply.text:
                self.last_reply = reply.text

            if reply.pcm16 and self.duplex is not None:
                self._speaking = True
                self.turns += 1
                try:
                    chunk = int(self.settings.sample_rate_out * 0.04) * 2
                    data = reply.pcm16
                    for i in range(0, len(data), chunk):
                        if not self._speaking:
                            break
                        await self.duplex.push_tts_pcm(
                            data[i : i + chunk],
                            reply.sample_rate,
                            finish=False,
                        )
                        await asyncio.sleep(0.02)
                    if self._speaking:
                        await self.duplex.push_tts_pcm(b"", reply.sample_rate, finish=True)
                finally:
                    self._speaking = False

    async def speak_text(self, text: str) -> dict[str, Any]:
        """快捷开口：Live 走 realtimeInput.text；级联走 TTS。"""
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "text required"}

        if self.live_mode:
            speak = getattr(self.backend, "speak_text", None)
            if speak is not None:
                await speak(text)
                self.memory.append(
                    "assistant",
                    text,
                    user_key="api",
                    channel_key=f"{self._area}/{self._channel}",
                )
                self.last_reply = text
                # 轮次不在这里计：模型出声后会推 turnComplete，由 on_turn_end 计一次。
                # 这里也 +1 的话，一次 /voice/speak 会被记成两轮。
                return {"ok": True, "chars": len(text), "mode": "live"}

        if not hasattr(self.backend, "tts"):
            return {"ok": False, "error": "backend does not support tts"}
        self.memory.append(
            "assistant",
            text,
            user_key="api",
            channel_key=f"{self._area}/{self._channel}",
        )
        pcm, rate = await self.backend.tts(text)  # type: ignore[attr-defined]
        if self.duplex is not None and pcm:
            self._speaking = True
            try:
                chunk = int(self.settings.sample_rate_out * 0.04) * 2
                for i in range(0, len(pcm), chunk):
                    if not self._speaking:
                        break
                    await self.duplex.push_tts_pcm(pcm[i : i + chunk], rate, finish=False)
                    await asyncio.sleep(0.02)
                if self._speaking:
                    await self.duplex.push_tts_pcm(b"", rate, finish=True)
            finally:
                self._speaking = False
        self.last_reply = text
        self.turns += 1
        return {"ok": True, "chars": len(text), "pcm_bytes": len(pcm or b""), "mode": "cascade"}

    def update_persona(self, persona: str) -> None:
        self.settings.persona = str(persona or self.settings.persona)
        self.memory.set_persona(self.settings.persona)
