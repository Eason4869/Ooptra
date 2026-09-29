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
        self._vad = EnergyVad(
            VadvConfig(
                sample_rate=settings.sample_rate_in,
                silence_ms=settings.silence_ms,
                max_utterance_ms=settings.max_utterance_ms,
            )
        )
        self._user_buffers: dict[str, EnergyVad] = {}
        self._task: asyncio.Task | None = None
        self._busy = asyncio.Lock()
        self._speaking = False
        self._joined = False
        self._area = settings.area
        self._channel = settings.channel
        self.last_reply = ""
        self.last_user_text = ""
        self.turns = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

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
        while True:
            await asyncio.sleep(30)

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
            self._speaking = True
            self.turns += 1
            try:
                await duplex.push_tts_pcm(pcm, rate, finish=False)
            finally:
                pass

        async def on_text(text: str) -> None:
            self.last_reply = text

        setter_audio = getattr(self.backend, "set_audio_out", None)
        if setter_audio:
            setter_audio(on_audio)
        setter_text = getattr(self.backend, "set_text_out", None)
        if setter_text:
            setter_text(on_text)

    async def leave(self) -> dict[str, Any]:
        if self._bot is not None and self._joined:
            try:
                await self._bot.voice.leave()
            except Exception:
                logger.debug("voice.leave failed", exc_info=True)
        self._joined = False
        self._user_buffers.clear()
        self._vad.reset()
        self._speaking = False
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
            # Live：持续灌入，模型自己做打断/回合
            if self._speaking and self.settings.barge_in:
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
                self.turns += 1
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
