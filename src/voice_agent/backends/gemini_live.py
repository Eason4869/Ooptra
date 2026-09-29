"""Gemini Live（Multimodal Live / BidiGenerateContent）端到端语音后端。

设计目标：语音进、语音出，不在中间落成完整文本再合成（Live）。
会话建立后持续把远端 PCM 写入 realtimeInput，把服务端音频 chunk 推回房间。

会话生命周期（这里曾经出过 B3）：
  * ``_session_loop`` 退出时必须回收 ``_ws`` / ``_session_task``，否则
    ``session_active`` 对已死的 socket 恒为 True，``start_session`` 变成空操作，
    音频全进黑洞。
  * ``_ready`` 只表示「setupComplete 已收到」，不再兼作「循环已结束」的唤醒信号。
  * 旧的循环退出时只清理「仍属于自己」的会话，避免误伤刚建好的新会话。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

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

    #: 会话意外断开后，后台重连前的等待秒数
    reconnect_delay: float = 1.0

    def __init__(self, settings, memory) -> None:
        self.settings = settings
        self.memory = memory
        self._ws = None
        self._session_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
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
        """会话真的可用吗——socket 在、未主动关闭、循环仍在跑。"""
        task = self._session_task
        return (
            self._ws is not None
            and not self._closed
            and task is not None
            and not task.done()
        )

    async def start_session(self) -> None:
        if self.session_active:
            return
        key = (self.settings.gemini_api_key or "").strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY / gemini.api_key 未配置（Live 模式必需）")

        from voice_agent.settings import resolve_agent_proxy_url
        from voice_agent.ws_transport import open_live_ws

        # 上一轮可能留下未回收的会话（服务端断开、setup 超时、异常退出）
        await self._reset_session()
        await self._cancel_reconnect()

        self._closed = False
        self._ready.clear()
        endpoint = str(
            getattr(self.settings, "gemini_base_url", "") or DEFAULT_LIVE_WS
        ).strip() or DEFAULT_LIVE_WS
        url = f"{endpoint}?key={key}"
        proxy = resolve_agent_proxy_url(getattr(self.settings, "proxy", "") or "")

        ws = await open_live_ws(url, proxy=proxy)
        self._ws = ws
        self._session_task = asyncio.create_task(
            self._session_loop(), name="gemini-live-session"
        )

        try:
            # setup：系统指令 + 音频输入输出
            await self._send_setup()
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except Exception:
            # 回滚，不留「_ws 已设但未 ready」的中间态
            await self._reset_session()
            raise
        if not self.session_active:
            await self._reset_session()
            raise RuntimeError("Gemini Live 会话建立后立即断开（请检查代理与 API key）")
        logger.info("Gemini Live session ready model=%s", self.settings.gemini_model)

    async def _reset_session(self) -> None:
        """回收当前会话：取消循环、关掉 socket、清空状态。可重复调用。"""
        task = self._session_task
        ws = self._ws
        self._session_task = None
        self._ws = None
        self._ready.clear()
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def close(self) -> None:
        self._closed = True
        await self._cancel_reconnect()
        await self._reset_session()

    async def _cancel_reconnect(self) -> None:
        """取消后台重连并**等它真的结束**——只 cancel 不 await 会留下悬空任务。"""
        task = self._reconnect_task
        self._reconnect_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def aclose(self) -> None:
        await self.close()

    def _schedule_reconnect(self) -> None:
        """音频热路径不能阻塞，断线后交给后台任务重连。"""
        if self._closed:
            return
        task = self._reconnect_task
        if task is not None and not task.done():
            return
        self._reconnect_task = asyncio.create_task(
            self._reconnect(), name="gemini-live-reconnect"
        )

    async def _reconnect(self) -> None:
        try:
            await asyncio.sleep(self.reconnect_delay)
            if self.session_active:
                return
            await self.start_session()
            logger.info("Gemini Live session reconnected")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Gemini Live reconnect failed: %s", exc)

    # ------------------------------------------------------------------
    # 协议
    # ------------------------------------------------------------------

    async def _send(self, payload: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None or self._closed:
            raise RuntimeError("Live session not connected")
        if getattr(ws, "closed", False):
            raise RuntimeError("Live session transport closed")
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
        """把远端麦克风 PCM 持续灌入 Live 会话（真正的听）。

        这是热路径（每帧都会调），断线时只标记 + 后台重连，不做同步重连；
        但**一定**会打 WARNING，不再像以前那样吞成 debug 造成无声黑洞。
        """
        if not pcm16 or self._closed:
            return
        if not self.session_active:
            await self.start_session()
        mime = f"audio/pcm;rate={int(sample_rate or self._in_sample)}"
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
        except Exception as exc:
            logger.warning("live audio push failed (%s); scheduling reconnect", exc)
            await self._reset_session()
            self._schedule_reconnect()

    async def interrupt(self) -> None:
        """barge-in：告诉模型用户抢话，丢掉当前响应。"""
        if not self.session_active:
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
            # 唤醒可能还在等 ready 的 start_session，别让它挂到超时
            self._ready.set()
            # 只有本循环仍是「当前会话」时才清理：旧循环不得误伤新会话
            owns_session = self._ws is ws
            if owns_session:
                self._ws = None
                self._session_task = None
                self._ready.clear()
                logger.info("Gemini Live session ended")
            with contextlib.suppress(Exception):
                await ws.close()
            if owns_session and not self._closed:
                self._schedule_reconnect()

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
                with contextlib.suppress(ValueError):
                    rate = int(mime.split("rate=")[1].split(";")[0].strip())
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
        """让模型「口头」说一句：以文本输入交给 Live。

        会话已死时**真重连一次再发**，失败就抛出去（调用方要能看到错误，
        不能像以前那样静默吞掉后返回 500）。
        """
        text = (text or "").strip()
        if not text:
            return
        if not self.session_active:
            await self.start_session()
        payload = {"realtimeInput": {"text": text}}
        try:
            await self._send(payload)
        except Exception as exc:
            logger.warning("live speak failed (%s); reconnecting once", exc)
            await self._reset_session()
            await self.start_session()
            await self._send(payload)


class OpenAiRealtimeBackend(GeminiLiveBackend):
    """OpenAI Realtime 骨架：协议不同，先复用 Live 会话接口占位。"""

    name = "openai_realtime"

    async def _send_setup(self) -> None:
        raise NotImplementedError(
            "OpenAI Realtime 协议尚未接入；请使用 backend=gemini_live"
        )
