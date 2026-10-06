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
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from voice_agent.backends.base import VoiceBackend, VoiceReply

logger = logging.getLogger(__name__)

# Google AI Studio / Gemini API 的 BidiGenerateContent WebSocket 端点
DEFAULT_LIVE_WS = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

AudioOutHandler = Callable[[bytes, int], Awaitable[None] | None]
#: 回合结束回调：参数为「是否被抢话打断」。模型说完是 False，被 barge-in 打断是 True。
TurnOutHandler = Callable[[bool], Awaitable[None] | None]

#: 追加在人格之后的固定语言约束。
#:
#: Live 的原生音频模型**不能**用 ``speechConfig.languageCode`` 锁语言 —— 官方文档
#: 原文：「Explicitly setting a language code is not supported for native audio
#: output models」，它按输入音频自动选语言。而我们的输入是**整个语音房间**的混音
#: （``listen_only_uids`` 默认空 = 谁的音频都吞），有人夹英文、有歌曲、有噪声时
#: 自动选语言就会翻车，现象就是「语言时不时乱切换」。
#:
#: 提示词是唯一可用的杠杆，所以这里**在人格之后追加**一条硬约束：人格是用户可随时
#: 改写/清空的配置项，这条不能跟着丢。放在最后是因为指令的收尾位置权重更高。
LANGUAGE_GUARD = (
    "\n\n# 语言（最高优先级）\n"
    "无论听到什么语言、方言、外语、歌曲还是噪声，你一律只用中文普通话回答，"
    "不要切换成英文或其他语言。"
)


#: 自动 VAD 的端点静音判定窗口。默认值偏短，语音房里自然停顿多，
#: 调大一点模型不会在人换气的间隙抢话。
LIVE_SILENCE_MS = 800
#: 语音起点前保留的音频长度，避免把词头切掉。
LIVE_PREFIX_PADDING_MS = 300


def _realtime_input_config() -> dict[str, Any]:
    """Live 的输入侧配置：**禁止服务端自动抢话**。

    为什么必须关掉（2026-09-30 实测）：灌给服务端的是**整个语音房间的混流**，而
    服务端的自动 VAD 只要认出「有人在说话」就取消正在生成的回复。热闹的房间里
    「有人在说话」是常态 —— 实测投喂一段真语音，**从 0.02（远处背景人声）到
    0.15（贴麦）的任何音量都会打断 bot**，于是 bot 一句完整的话都说不完。

    调灵敏度救不了：`start_of_speech_sensitivity` 降到 LOW 后六个音量档位的打断
    次数**一模一样**。灵敏度的含义是「VAD 要多确信才算语音」，而背景人声本来就是
    真语音，再低的灵敏度也拦不住。

    关掉之后，抢话改由**客户端**判定（``VoiceAgent._on_remote_pcm`` 的
    ``barge_in_hold_ms`` 门限）—— 只有某人连着说了足够久才让路。注意
    ``NO_INTERRUPTION`` 只是「不打断生成」，**不是「听不见」**：实测同一配置下
    输入照常转写、模型照常回应用户。

    载荷拼写是实测钉死的（**写错会让整个连接以 close_code=1007 断开**，
    不是「配置没生效」）：
      * ``realtime_input_config`` / ``automatic_activity_detection`` 用 **snake_case**
        —— 这套接口**只认 snake_case**，``realtimeInputConfig`` 之类的 camelCase
        一律 1007（同一个 setup 里 ``generation_config`` 也是 snake，一致）；
      * ``activity_handling`` 取值 ``NO_INTERRUPTION``（伪造值会被 1007 拒，说明
        枚举真的在校验，不是被静默忽略）。
    """
    return {
        "automatic_activity_detection": {
            "prefix_padding_ms": LIVE_PREFIX_PADDING_MS,
            "silence_duration_ms": LIVE_SILENCE_MS,
        },
        "activity_handling": "NO_INTERRUPTION",
    }


def live_url_has_key(url: str) -> bool:
    """URL 的查询串里有没有非空的 ``key``。"""
    return bool((parse_qs(urlsplit(url).query).get("key") or [""])[0].strip())


def build_live_url(endpoint: str, api_key: str) -> str:
    """把 API key 拼进 Live 端点 URL —— **幂等**，永远不会出现两个 ``?key=``。

    ``gemini.base_url`` 里直接带 key 是合法配置（Google 文档给的就是
    ``...BidiGenerateContent?key=API_KEY`` 这种形态）。旧代码无条件再拼一次
    ``?key=``，URL 变成 ``...?key=<k>?key=<k>``：服务端解析出的 key 长度翻倍，
    **不返回 error 帧、直接关 socket** —— 现象就是「bot 进房了但一句话不说」，
    日志里连 ``Gemini Live session ready`` 都不会出现（2026-09-29 实测踩过）。

    显式配置的 ``api_key`` 优先：它非空时覆盖 URL 里的同名参数；为空时保留
    URL 自带的 key。
    """
    endpoint = str(endpoint or "").strip() or DEFAULT_LIVE_WS
    key = str(api_key or "").strip()
    if not key:
        return endpoint

    parts = urlsplit(endpoint)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "key"]
    query.append(("key", key))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


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
        self._turn_out: TurnOutHandler | None = None
        self._reply_out = None
        self.reply_active = False
        self._announcement = False
        # start_session 可能被并发调用（push_audio 在音频热路径上也会调它），
        # 而它开头就 _reset_session() —— 没有这把锁，任何一次非活跃窗口都会
        # 让每个音频帧各建一次会话，互相把对方的 socket 拆掉。
        self._start_lock = asyncio.Lock()
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

    def set_reply_out(self, handler) -> None:
        self._reply_out = handler

    def _set_reply_active(self, active: bool) -> None:
        self.reply_active = active
        if self._reply_out is not None:
            self._reply_out(active)

    def set_turn_out(self, handler: TurnOutHandler | None) -> None:
        """注册「一个回合结束了」的回调（``interrupted=True`` 表示被抢话打断）。

        在此之前，``turnComplete``/``interrupted`` 这条边界信息只被用来写记忆和
        自增一个没人读的计数器，**从不外泄** —— 上层只好拿「收到音频分片」当
        「正在说话」，于是这个状态一旦置上就再也回落不了。
        """
        self._turn_out = handler

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
        async with self._start_lock:
            # 排队等锁期间，先到的那次可能已经把会话建好了
            if self.session_active:
                return
            await self._start_session_locked()

    async def _start_session_locked(self) -> None:
        from voice_agent.settings import resolve_agent_proxy_url
        from voice_agent.ws_transport import open_live_ws

        endpoint = str(
            getattr(self.settings, "gemini_base_url", "") or DEFAULT_LIVE_WS
        ).strip() or DEFAULT_LIVE_WS
        # key 可以来自 gemini.api_key，也可以直接写在 base_url 里（两者取其一即可）
        url = build_live_url(endpoint, getattr(self.settings, "gemini_api_key", "") or "")
        if not live_url_has_key(url):
            raise RuntimeError("GEMINI_API_KEY / gemini.api_key 未配置（Live 模式必需）")

        # 上一轮可能留下未回收的会话（服务端断开、setup 超时、异常退出）
        await self._reset_session()
        await self._cancel_reconnect()

        self._closed = False
        self._ready.clear()
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
        self._set_reply_active(False)
        self._announcement = False
        self._last_user_text = ""
        self._last_reply = ""
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

    async def reset_reply_session(self) -> None:
        """Discard an uncancellable turn; lazily rebuild on the next input."""
        await self.close()
        self._closed = False

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
                    "parts": [{"text": (self.settings.persona or "") + LANGUAGE_GUARD}]
                },
                "input_audio_transcription": {},
                "output_audio_transcription": {},
                "realtime_input_config": _realtime_input_config(),
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
        """barge-in 的**客户端侧**动作：本地静音即可，不再向服务端发信号。

        这里以前发 ``realtimeInput.audioStreamEnd``，但那个字段的语义是
        **「用户说完了，立刻处理并回答」**（官方文档：客户端 VAD 检测到句尾时发，
        用来省掉服务端静音等待）。用它来抢话正好说反了：用户**刚开始**说话时发它，
        等于逼模型把当时缓冲区里的音频碎片当成一个完整回合去回答 —— 一段没有内容
        的输入，模型只能瞎猜，语言就是这里开始飘的（实测同一会话里中英文乱切）。

        当前做法：setup 里设了 ``activity_handling: NO_INTERRUPTION``（见
        ``_realtime_input_config``），**服务端不再因为听到人声就取消模型的回合**。
        抢话完全由 agent 侧判定 —— 某人连续说话满 ``barge_in_hold_ms`` 才算数
        （房间越吵门限越大），命中后 ``duplex.stop_tts()`` 清掉本地已排期的播放，
        就是全部动作。所以这里不需要、也不应该再往服务端发任何东西。

        保留这个方法是为了接口稳定（agent 无条件调用），它现在是**有意的空操作**。
        """
        logger.debug("live interrupt: 客户端侧无操作（抢话由 agent 侧门限判定 + 清本地队列）")

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
        else:
            # 读循环**自然结束**（迭代到头、没抛异常、也没收到 CLOSE 帧）——
            # 这是「会话静悄悄消失」的可疑路径，单独标记出来才好定位。
            logger.info("Live 读循环结束：ws 迭代到头，未抛异常")
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
            # toolCall 等以后再接。**但必须留痕**：服务端的会话生命周期消息
            # （goAway / sessionResumptionUpdate 之类）正是走这条路，静默 return
            # 会让「会话每 20~25 秒断一次」变成无头案 —— 2026-10-01 实测踩到：
            # 断开时既没有 ws 关闭日志、也没有异常，只留一句 session ended。
            #
            # 但**只记有信息量的**：空包（``{}``）、空的 ``serverContent``、
            # ``voiceActivity`` 都是心跳级噪音 —— 光 voiceActivity 一项实测就刷掉
            # ~100 行/分钟，把真正的断线线索埋了。过滤掉这三类之后，剩下的
            # （goAway / sessionResumptionUpdate / toolCall）才是要看的。
            interesting = {
                k: v for k, v in msg.items() if k not in ("voiceActivity", "serverContent")
            }
            if not interesting:
                return
            logger.info(
                "Live 服务端消息（当前未处理）：%s",
                {k: str(v)[:160] for k, v in interesting.items()},
            )
            return

        # 转写（可选进记忆）
        input_tr = server.get("inputTranscription") or {}
        output_tr = server.get("outputTranscription") or {}
        if input_tr.get("text"):
            self._set_reply_active(True)
            self._last_user_text = (self._last_user_text + input_tr["text"]).strip()
        if output_tr.get("text"):
            self._last_reply = (self._last_reply + output_tr["text"]).strip()

        turn = server.get("modelTurn") or {}
        if turn or output_tr.get("text"):
            self._set_reply_active(True)
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
            self._set_reply_active(False)
            self._turns += 1
            # 转写落日志：语言乱切换这类问题**只能**从这里看出来（模型到底听到了
            # 什么、又用什么语言回答）。记忆里本来就存了这两段文本，日志不增加暴露。
            if self._last_user_text or self._last_reply:
                logger.info(
                    "Live 回合：用户=%r 回复=%r%s",
                    self._last_user_text[:80],
                    self._last_reply[:80],
                    "（被抢话打断）" if server.get("interrupted") else "",
                )
            # 回合边界：先通知上层（它据此把「正在说话」落回 False、结束一次轮次），
            # 再写记忆。被抢话时上层还要就地丢掉本地已排期的音频。
            turn_handler = self._turn_out
            if turn_handler is not None:
                try:
                    result = turn_handler(bool(server.get("interrupted")))
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.debug("turn out handler failed", exc_info=True)
            if self._last_user_text or self._last_reply:
                try:
                    if self._last_user_text and not self._announcement:
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
            self._announcement = False

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
        self._set_reply_active(True)
        try:
            await self._send(payload)
        except Exception as exc:
            logger.warning("live speak failed (%s); reconnecting once", exc)
            await self._reset_session()
            await self.start_session()
            await self._send(payload)

    async def speak_announcement(self, kind: str, template: str) -> None:
        from voice_agent.announcements import announcement_instruction

        if not self.session_active:
            await self.start_session()
        self._last_user_text = ""
        self._last_reply = ""
        self._announcement = True
        self._set_reply_active(True)
        await self._send({"realtimeInput": {"text": announcement_instruction(kind, template)}})


class OpenAiRealtimeBackend(GeminiLiveBackend):
    """OpenAI Realtime 骨架：协议不同，先复用 Live 会话接口占位。"""

    name = "openai_realtime"

    async def _send_setup(self) -> None:
        raise NotImplementedError(
            "OpenAI Realtime 协议尚未接入；请使用 backend=gemini_live"
        )
