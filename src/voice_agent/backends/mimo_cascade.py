"""MiMo 级联：ASR → Chat LLM → TTS（stream + pcm），适合中文语音房。"""

from __future__ import annotations

import base64
import json
import logging
import struct
import wave
from io import BytesIO

from voice_agent.backends.base import VoiceBackend, VoiceReply

logger = logging.getLogger(__name__)


def _aiohttp():
    import aiohttp

    return aiohttp


def pcm16_to_wav(pcm16: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)
    return buf.getvalue()


def wav_to_pcm16(data: bytes) -> tuple[bytes, int]:
    with wave.open(BytesIO(data), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if sampwidth != 2:
        # 仅处理 16bit；其它位深粗暴按 8bit/32bit 转换兜底
        if sampwidth == 1:
            samples = [(b - 128) << 8 for b in raw]
            raw = struct.pack("<" + "h" * len(samples), *samples)
        elif sampwidth == 4:
            count = len(raw) // 4
            ints = struct.unpack("<" + "i" * count, raw[: count * 4])
            samples = [max(-32767, min(32767, v >> 16)) for v in ints]
            raw = struct.pack("<" + "h" * len(samples), *samples)
        else:
            raise ValueError(f"unsupported wav sampwidth: {sampwidth}")
    if channels > 1:
        # 简单取左声道
        count = len(raw) // 2
        samples = struct.unpack("<" + "h" * count, raw[: count * 2])
        mono = samples[::channels]
        raw = struct.pack("<" + "h" * len(mono), *mono)
    return raw, rate


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    if src_rate == dst_rate or not pcm:
        return pcm
    count = len(pcm) // 2
    samples = struct.unpack("<" + "h" * count, pcm[: count * 2])
    if not samples:
        return b""
    duration = len(samples) / float(src_rate)
    out_len = max(1, int(duration * dst_rate))
    out: list[int] = []
    for i in range(out_len):
        pos = i * (len(samples) - 1) / max(1, out_len - 1)
        i0 = int(pos)
        i1 = min(len(samples) - 1, i0 + 1)
        frac = pos - i0
        val = samples[i0] * (1 - frac) + samples[i1] * frac
        out.append(max(-32767, min(32767, int(val))))
    return struct.pack("<" + "h" * len(out), *out)


class MimoCascadeBackend(VoiceBackend):
    name = "mimo_cascade"

    def __init__(self, settings, memory) -> None:
        self.settings = settings
        self.memory = memory
        self._session = None  # aiohttp.ClientSession，懒加载

    def _proxy_url(self) -> str | None:
        from voice_agent.settings import resolve_agent_proxy_url

        return resolve_agent_proxy_url(getattr(self.settings, "proxy", "") or "")

    async def _http(self):
        if self._session is None or self._session.closed:
            aiohttp = _aiohttp()
            timeout = aiohttp.ClientTimeout(total=90, sock_connect=15, sock_read=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    def _headers(self) -> dict[str, str]:
        key = (self.settings.mimo_api_key or "").strip()
        if not key:
            raise RuntimeError("MIMO_API_KEY / mimo.api_key 未配置")
        return {
            "api-key": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    async def asr(self, pcm16: bytes, sample_rate: int) -> str:
        wav = pcm16_to_wav(pcm16, sample_rate)
        b64 = base64.b64encode(wav).decode("ascii")
        body = {
            "model": self.settings.mimo_asr_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": f"data:audio/wav;base64,{b64}"},
                        }
                    ],
                }
            ],
            "asr_options": {"language": "auto"},
        }
        session = await self._http()
        url = self.settings.mimo_base_url.rstrip("/") + "/chat/completions"
        async with session.post(
            url, headers=self._headers(), json=body, proxy=self._proxy_url()
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"ASR failed HTTP {resp.status}: {data}")
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()

    async def chat(self, user_text: str, *, user_key: str = "") -> str:
        history = self.memory.as_messages(user_key=user_key, limit=self.settings.memory_max_turns)
        messages: list[dict[str, str]] = [{"role": "system", "content": self.settings.persona}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        body = {
            "model": self.settings.mimo_llm_model,
            "messages": messages,
            "stream": False,
        }
        session = await self._http()
        url = self.settings.mimo_base_url.rstrip("/") + "/chat/completions"
        async with session.post(
            url, headers=self._headers(), json=body, proxy=self._proxy_url()
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"LLM failed HTTP {resp.status}: {data}")
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str(((choices[0] or {}).get("message") or {}).get("content") or "").strip()

    async def tts(self, text: str) -> tuple[bytes, int]:
        if not text.strip():
            return b"", self.settings.sample_rate_out
        body = {
            "model": self.settings.mimo_tts_model,
            "messages": [
                {"role": "user", "content": "自然对话，口语化，不要播音腔。"},
                {"role": "assistant", "content": text},
            ],
            "audio": {"format": "pcm", "voice": self.settings.mimo_tts_voice},
            "stream": True,
        }
        session = await self._http()
        url = self.settings.mimo_base_url.rstrip("/") + "/chat/completions"
        chunks: list[bytes] = []
        async with session.post(
            url, headers=self._headers(), json=body, proxy=self._proxy_url()
        ) as resp:
            if resp.status >= 400:
                raw = await resp.text()
                raise RuntimeError(f"TTS failed HTTP {resp.status}: {raw}")
            async for line in resp.content:
                if not line:
                    continue
                text_line = line.decode("utf-8", errors="ignore").strip()
                if not text_line.startswith("data:"):
                    continue
                payload = text_line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = ((event.get("choices") or [{}])[0] or {}).get("delta") or {}
                audio = delta.get("audio") or {}
                data_b64 = audio.get("data") if isinstance(audio, dict) else None
                if data_b64:
                    try:
                        chunks.append(base64.b64decode(data_b64))
                    except Exception:
                        logger.debug("bad tts chunk", exc_info=True)
        pcm = b"".join(chunks)
        # MiMo TTS pcm 默认 24k；若长度异常则按配置输出率处理
        return pcm, self.settings.sample_rate_out

    async def handle_utterance(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        user_key: str = "",
        channel_key: str = "",
    ) -> VoiceReply:
        if not pcm16:
            return VoiceReply()
        text = await self.asr(pcm16, sample_rate)
        if not text.strip():
            return VoiceReply(user_text=text)
        self.memory.append("user", text, user_key=user_key, channel_key=channel_key)
        reply_text = await self.chat(text, user_key=user_key)
        if not reply_text.strip():
            return VoiceReply(user_text=text, text="", user_key=user_key)
        self.memory.append(
            "assistant",
            reply_text,
            user_key=user_key,
            channel_key=channel_key,
        )
        pcm_out, rate_out = await self.tts(reply_text)
        pcm_out = resample_pcm16(pcm_out, rate_out, self.settings.sample_rate_out)
        return VoiceReply(
            user_text=text,
            text=reply_text,
            pcm16=pcm_out,
            sample_rate=self.settings.sample_rate_out,
            user_key=user_key,
            raw={"stored": True},
        )

    async def aclose(self) -> None:
        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()
