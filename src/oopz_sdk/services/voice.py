from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from oopz_sdk import models
from oopz_sdk.services import BaseService
from oopz_sdk.transport.voice_browser import BrowserVoiceTransport

logger = logging.getLogger(__name__)


class Voice(BaseService):
    """High-level voice orchestration service.

    Responsibilities:
    - call Oopz `enter_channel(..., channel_type="VOICE")` to obtain `ChannelSign`
    - join/publish via `BrowserVoiceTransport`
    - periodically re-send the identity bridge payload used by Oopzbot
    """

    def __init__(self, owner, config, transport, signer, cache):
        super().__init__(owner, config, transport, signer, cache)
        self.backend = BrowserVoiceTransport(config)
        self._current_sign: models.ChannelSign | None = None
        self._current_area: str | None = None
        self._current_channel: str | None = None
        self._current_uid: str | None = None
        self._identity_task: asyncio.Task | None = None
        self._join_generation = 0


    @property
    def current_sign(self) -> models.ChannelSign | None:
        return self._current_sign

    # ------------------------------------------------------------------
    # 成员实时静音状态（转发给 WebUI / 插件读）
    # ------------------------------------------------------------------

    def voice_states(self) -> dict[str, dict]:
        """房间内成员最近一次上报的静音状态；没人广播过就是空表。"""
        return self.backend.voice_states()

    @property
    def voice_state_received(self) -> int:
        """本房累计收到的广播条数（0 = 数据源没在发，界面继续显示未知）。"""
        return self.backend.voice_state_received

    async def _cleanup_failed_join(self, area: str, channel: str) -> None:
        """
        `enter_channel` 成功后若浏览器/Agora 未就绪或加入失败，服务端可能仍认为在语音房；
        尽力退出 Agora 并调用服务端 `leave_voice_channel`，避免残留状态。
        """
        generation = self._join_generation

        async def rollback() -> None:
            backend_ok = membership_ok = False
            try:
                await asyncio.wait_for(self.backend.leave(), timeout=5)
                backend_ok = True
            except Exception:
                logger.debug("backend.leave after failed Voice.join", exc_info=True)
            try:
                result = await asyncio.wait_for(self._bot.channels.leave_voice_channel(
                    channel=channel, area=area, target=self._config.person_uid,
                ), timeout=5)
                membership_ok = result is None or bool(getattr(result, "ok", True))
            except Exception:
                logger.debug("leave_voice_channel after failed Voice.join", exc_info=True)
            if (backend_ok and membership_ok and self._join_generation == generation
                    and self._current_area == area and self._current_channel == channel):
                self._current_sign = None
                self._current_area = self._current_channel = self._current_uid = None

        task = asyncio.create_task(rollback(), name="voice-failed-join-rollback")
        cancelled: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                # Every additional cancellation must still wait for bounded rollback.
                cancelled = cancelled or exc
        task.result()
        if cancelled is not None:
            raise cancelled

    async def start(self) -> None:
        await self.backend.start()

    async def close(self) -> None:
        await self._stop_identity_heartbeat()
        await self.backend.close()

    async def join(
        self,
        *,
        area: str,
        channel: str,
        from_area: str = "",
        from_channel: str = "",
        rtc_uid: str | int | None = None,
    ) -> models.ChannelSign:
        if rtc_uid is None:
            rtc_uid = (await self._bot.person.get_self_detail()).pid
        rtc_uid = str(rtc_uid)
        sign = await self._bot.channels.enter_channel(
            channel=channel,
            area=area,
            channel_type="VOICE",
            from_channel=from_channel,
            from_area=from_area,
            pid=rtc_uid,
        )
        # Server membership already exists; retain its target until rollback succeeds.
        self._join_generation += 1
        self._current_sign = sign
        self._current_area = area
        self._current_channel = channel
        self._current_uid = rtc_uid
        if not sign.rtc_token or not sign.rtc_channel_name:
            await self._cleanup_failed_join(area, channel)
            raise RuntimeError("enter_channel returned no supplierSign/roomId")

        try:
            ok = await self.backend.join(
                app_id=self._config.agora_app_id,
                token=sign.rtc_token,
                room_id=sign.rtc_channel_name,
                uid=rtc_uid,
                oopz_uid=self._config.person_uid
            )
        except (Exception, asyncio.CancelledError):
            await self._cleanup_failed_join(area, channel)
            raise

        if not ok:
            await self._cleanup_failed_join(area, channel)
            raise RuntimeError("failed to join Agora room from browser backend")

        self._current_sign = sign
        self._current_area = area
        self._current_channel = channel
        self._current_uid = rtc_uid

        try:
            # 首次发送身份绑定：浏览器端没有可用 WebSocket 时 agoraSendIdentity 会
            # 返回 {ok:false}，BrowserVoiceTransport.send_identity 因此返回 False。
            # 这种情况下机器人虽然进了 Agora 房间，但服务端/其他客户端没法把 Oopz
            # UID 与 Agora UID 对齐，必须视为加入失败、完整回滚；心跳循环里的后续
            # 失败（_send_identity_once）可以容忍，记录 debug 日志即可。
            sent = await self._send_identity_once()
            if not sent:
                raise RuntimeError(
                    "voice identity bridge not ready: "
                    "browser WebSocket missing or agoraSendIdentity returned ok=false"
                )
            await self._start_identity_heartbeat()
        except (Exception, asyncio.CancelledError):
            await self._stop_identity_heartbeat()
            await self._cleanup_failed_join(area, channel)
            raise
        return sign

    async def leave(self) -> None:
        await self._stop_identity_heartbeat()
        await self.backend.leave()
        if self._current_area and self._current_channel:
            result = await self._bot.channels.leave_voice_channel(
                channel=self._current_channel,
                area=self._current_area,
                target=self._config.person_uid,
            )
            if result is not None and not getattr(result, "ok", True):
                raise RuntimeError(getattr(result, "message", "") or "voice membership leave rejected")
        # Only clear ownership once both the RTC and membership leave succeed.
        # A partial failure retains enough information for a bounded retry.
        self._current_sign = None
        self._current_area = None
        self._current_channel = None
        self._current_uid = None

    async def play_url(self, url: str) -> dict[str, Any]:
        if not url.strip():
            raise ValueError("url cannot be empty")
        return await self.backend.play_url(url)

    async def play_file(self, file_path: str, *, mime_type: str | None = None) -> dict[str, Any]:
        if not file_path.strip():
            raise ValueError("file_path cannot be empty")
        return await self.backend.play_file(file_path, mime_type=mime_type)

    async def play_bytes(self, data: bytes, *, mime_type: str = "audio/mpeg") -> dict[str, Any]:
        if not data:
            raise ValueError("data cannot be empty")
        return await self.backend.play_bytes(data, mime_type=mime_type)

    async def stop(self) -> None:
        await self.backend.stop_audio()

    async def pause(self) -> bool:
        return await self.backend.pause()

    async def resume(self) -> bool:
        return await self.backend.resume()

    async def seek(self, seconds: float) -> bool:
        return await self.backend.seek(seconds)

    async def set_volume(self, volume: int) -> bool:
        return await self.backend.set_volume(volume)

    async def get_state(self) -> str:
        return await self.backend.get_state()

    async def get_current_time(self) -> float:
        return await self.backend.get_current_time()

    async def _send_identity_once(self) -> bool:
        """向浏览器桥发送身份绑定。返回 True 代表浏览器端 ack 成功。

        首次失败需要在 ``join`` 里触发回滚，后续心跳循环里失败只记日志、等下次重试。
        """
        if not self._current_uid:
            return False
        try:
            ok = await self.backend.send_identity(self._config.person_uid, self._current_uid)
        except Exception:
            logger.debug("send identity failed", exc_info=True)
            return False
        return bool(ok)

    async def _start_identity_heartbeat(self) -> None:
        await self._stop_identity_heartbeat()

        async def _loop() -> None:
            while True:
                await asyncio.sleep(10)
                await self._send_identity_once()

        self._identity_task = asyncio.create_task(_loop(), name="oopz_voice_identity_heartbeat")

    async def _stop_identity_heartbeat(self) -> None:
        task = self._identity_task
        self._identity_task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
