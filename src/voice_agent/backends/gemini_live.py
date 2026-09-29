"""Gemini Live（Multimodal Live / BidiGenerateContent）端到端语音后端。

设计目标：语音进、语音出，不在中间落成完整文本再合成（Live）。
会话建立后持续把远端 PCM 写入 realtimeInput，把服务端音频 chunk 推回房间。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Awaitable, Callable

from voice_agent.backends.base import VoiceBackend, VoiceReply

logger = logging.getLogger(__name__)

# Google AI Studio / Gemini API 的 BidiGenerateContent WebSocket 端点
DEFAULT_LIVE_WS = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

AudioOutHandler = Callable[[bytes, int], Awaitable[None] | None]


class GeminiLiveBackend(VoiceBackend):
    """常驻 Live 会话：PCM 双向流，不做「文-想-说」级联。"""

    name = "gemini_live"

    def __init__(self, settings, memory) -> None:
        self.settings = settings
        self.memory = memory
        self._ws = None
        self._session_task: asyncio.Task | None = None
        self._audio_out: AudioOutHandler | None = None
        self._text_out: Callable[[str], Awaitable[None] | None] | None = None
        self._ready = asyncio.Event()
        self._closed = False
        self._turns = 0
        self._last_user_text = ""
        self._last_reply = ""
        self._in_sample = int(getattr(settings, "sample_rate_in", 16000) or 16000)
        self._out_sample = int(getattr(settings, "sample_rate_out", 24000) or 24000)

    # ------------------------------------------------------------------
    # 生命周期 / 回调
    # ------------------------------------------------------------------

    def set_audio_out(self, handler: AudioOutHandler | None) -> None:
        self._audio_out = handler

    def set_text_out(self, handler) -> None:
        self._text_out = handler

    @property
    def session_active(self) -> bool:
        return self._ws is not None and not self._closed

    async def start_session(self) -> None:
        if self.session_active:
            return
        key = (self.settings.gemini_api_key or "").strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY / gemini.api_key 未配置（Live 模式必需）")

        try:
            import websockets
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Live 后端需要 websockets：pip install websockets"
            ) from exc

        self._closed = False
        self._ready.clear()
        url = f"{DEFAULT_LIVE_WS}?key={key}"
        self._ws = await websockets.connect(
            url,
            max_size=8 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        )
        self._session_task = asyncio.create_task(self._session_loop(), name="gemini-live-session")

        # setup：系统指令 + 音频输入输出
        await self._send_setup()
        await asyncio.wait_for(self._ready.wait(), timeout=15)
        logger.info("Gemini Live session ready model=%s", self.settings.gemini_model)

    async def close(self) -> None:
        self._closed = True
        task = self._session_task
        self._session_task = None
        ws = self._ws
        self._ws = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                logger.debug("live ws close failed", exc_info=True)

    async def aclose(self) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # 协议
    # ------------------------------------------------------------------

    async def _send(self, payload: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            raise RuntimeError("Live session not connected")
        await ws.send(json.dumps(payload, ensure_ascii=False))

    async def _send_setup(self) -> None:
        setup = {
            "setup": {
                "model": f"models/{self.settings.gemini_model}",
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": self.settings.gemini_voice or "Puck"
                            }
                        }
                    },
                },
                "system_instruction": {
                    "parts": [{"text": self.settings.persona or ""}]
                },
                "input_audio_transcription": {},
                "output_audio_transcription": {},
            }
        }
        await self._send(setup)

    async def push_audio(self, pcm16: bytes, sample_rate: int | None = None) -> None:
        """把远端麦克风 PCM 持续灌入 Live 会话（真正的听）。"""
        if not pcm16 or self._closed:
            return
        if self._ws is None:
            await self.start_session()
        mime = "audio/pcm;rate=%d" % int(sample_rate or self._in_sample)
        payload = {
            "realtimeInput": {
                "audio": {
                    "data": base64.b64encode(pcm16).decode("ascii"),
                    "mime_type": mime,
                }
            }
        }
        try:
            await self._send(payload)
        except Exception:
            logger.debug("push live audio failed", exc_info=True)

    async def interrupt(self) -> None:
        """barge-in：告诉模型用户抢话，丢掉当前响应。"""
        if self._ws is None:
            return
        try:
            await self._send({"realtimeInput": {"audioStreamEnd": True}})
        except Exception:
            logger.debug("live interrupt failed", exc_info=True)

    async def _session_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                if self._closed:
                    break
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._handle_server_msg(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Gemini Live session error")
        finally:
            self._ready.set()

    async def _handle_server_msg(self, msg: dict[str, Any]) -> None:
        if "setupComplete" in msg:
            self._ready.set()
            return

        server = msg.get("serverContent") or {}
        if not server:
            # toolCall 等以后再接
            return

        # 转写（可选进记忆）
        input_tr = server.get("inputTranscription") or {}
        output_tr = server.get("outputTranscription") or {}
        if input_tr.get("text"):
            self._last_user_text = (self._last_user_text + input_tr["text"]).strip()
        if output_tr.get("text"):
            self._last_reply = (self._last_reply + output_tr["text"]).strip()

        turn = server.get("modelTurn") or {}
        for part in turn.get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            data = inline.get("data")
            if not data:
                continue
            try:
                pcm = base64.b64decode(data)
            except Exception:
                continue
            rate = self._out_sample
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "")
            if "rate=" in mime:
                try:
                    rate = int(mime.split("rate=")[1].split(";")[0].strip())
                except ValueError:
                    pass
            handler = self._audio_out
            if handler is not None and pcm:
                result = handler(pcm, rate)
                if asyncio.iscoroutine(result):
                    await result

        if server.get("turnComplete") or server.get("interrupted"):
            self._turns += 1
            if self._last_user_text or self._last_reply:
                try:
                    if self._last_user_text:
                        self.memory.append("user", self._last_user_text, user_key="live")
                    if self._last_reply:
                        self.memory.append("assistant", self._last_reply, user_key="live")
                except Exception:
                    logger.debug("memory write failed", exc_info=True)
            text_handler = self._text_out
            if text_handler is not None and self._last_reply:
                result = text_handler(self._last_reply)
                if asyncio.iscoroutine(result):
                    await result
            self._last_user_text = ""
            self._last_reply = ""

    # ------------------------------------------------------------------
    # VoiceBackend 兼容接口（Live 走流式，handle_utterance 仅兜底）
    # ------------------------------------------------------------------

    async def handle_utterance(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        user_key: str = "",
        channel_key: str = "",
    ) -> VoiceReply:
        if pcm16:
            await self.push_audio(pcm16, sample_rate)
        return VoiceReply(user_text=self._last_user_text, text=self._last_reply, user_key=user_key)

    async def speak_text(self, text: str) -> None:
        """让模型「口头」说一句：以文本输入交给 Live。"""
        if not text.strip():
            return
        if self._ws is None:
            await self.start_session()
        await self._send(
            {
                "realtimeInput": {
                    "text": text,
                }
            }
        )


class OpenAiRealtimeBackend(GeminiLiveBackend):
    """OpenAI Realtime 骨架：协议不同，先复用 Live 会话接口占位。"""

    name = "openai_realtime"

    async def _send_setup(self) -> None:
        raise NotImplementedError(
            "OpenAI Realtime 协议尚未接入；请使用 backend=gemini_live"
        )
