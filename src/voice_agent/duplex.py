"""浏览器全双工桥：收远端 PCM、推 TTS PCM，复用 Playwright voice backend。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

RemotePcmHandler = Callable[[str, bytes, int], Awaitable[None] | None]


class VoiceDuplex:
    """包装 BrowserVoiceTransport，增加 subscribe/publish_pcm。"""

    def __init__(self, transport: Any) -> None:
        self._transport = transport
        self._pcm_queue: asyncio.Queue[tuple[str, bytes, int]] = asyncio.Queue(maxsize=200)
        self._handler: RemotePcmHandler | None = None
        self._pump_task: asyncio.Task | None = None

    @property
    def transport(self) -> Any:
        return self._transport

    def set_remote_pcm_handler(self, handler: RemotePcmHandler | None) -> None:
        self._handler = handler

    def enqueue_remote_pcm(self, uid: str, pcm: bytes, sample_rate: int) -> None:
        try:
            self._pcm_queue.put_nowait((uid, pcm, sample_rate))
        except asyncio.QueueFull:
            logger.debug("remote pcm queue full, drop chunk")

    async def start(self) -> None:
        await self._transport.start()
        self._transport.set_remote_pcm_callback(self.enqueue_remote_pcm)
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = asyncio.create_task(self._pump(), name="voice-duplex-pump")

    async def close(self) -> None:
        task = self._pump_task
        self._pump_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._transport.close()

    async def _pump(self) -> None:
        while True:
            uid, pcm, rate = await self._pcm_queue.get()
            handler = self._handler
            if handler is None:
                continue
            try:
                result = handler(uid, pcm, rate)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("remote pcm handler failed")

    async def enable_listen(self, enabled: bool = True) -> dict[str, Any]:
        return await self._transport.enable_listen(enabled)

    async def push_tts_pcm(
        self,
        pcm16: bytes,
        sample_rate: int,
        *,
        finish: bool = False,
    ) -> dict[str, Any]:
        if not pcm16 and not finish:
            return {"ok": True, "empty": True}
        return await self._transport.push_tts_pcm(pcm16, sample_rate, finish=finish)

    async def stop_tts(self) -> dict[str, Any]:
        return await self._transport.stop_tts()
