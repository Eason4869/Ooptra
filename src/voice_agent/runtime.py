"""语音 Agent 装配入口。"""

from __future__ import annotations

import logging
from typing import Any

from voice_agent.agent import VoiceAgent
from voice_agent.api import VoiceApiServer
from voice_agent.settings import load_voice_agent_settings

logger = logging.getLogger(__name__)


class VoiceRuntime:
    def __init__(self) -> None:
        self.agent_settings, self.api_settings = load_voice_agent_settings()
        self.agent = VoiceAgent(self.agent_settings, self.api_settings)
        self.api = VoiceApiServer(self.agent, self.api_settings)
        self._started = False

    @property
    def enabled(self) -> bool:
        return bool(self.agent_settings.enabled or self.api_settings.enabled)

    def bind_bot(self, bot: Any) -> None:
        self.agent.bind_bot(bot)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        # 独立 VOICE_API 端口默认关闭；语音接口已合并到 WebUI /api/*
        if self.api_settings.enabled and self.api_settings.port not in (0,):
            try:
                await self.api.start()
            except Exception:
                logger.exception("VOICE_API start failed")
        try:
            await self.agent.start()
        except Exception:
            logger.exception("voice agent start failed")

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        try:
            await self.agent.stop()
        except Exception:
            logger.exception("voice agent stop failed")
        try:
            await self.api.stop()
        except Exception:
            logger.exception("VOICE_API stop failed")


_runtime: VoiceRuntime | None = None


def get_voice_runtime() -> VoiceRuntime:
    global _runtime
    if _runtime is None:
        _runtime = VoiceRuntime()
    return _runtime
