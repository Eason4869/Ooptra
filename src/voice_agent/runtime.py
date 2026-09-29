"""语音 Agent 装配入口。"""

from __future__ import annotations

import logging
from typing import Any

from voice_agent.agent import VoiceAgent
from voice_agent.api import VoiceApiServer
from voice_agent.settings import apply_settings, load_voice_agent_settings

logger = logging.getLogger(__name__)

# 独立 VOICE_API 端口这些字段改了必须重启进程才能生效（socket 已经绑好了）
_API_RESTART_KEYS = ("host", "port")


class VoiceRuntime:
    def __init__(self) -> None:
        self.agent_settings, self.api_settings = load_voice_agent_settings()
        self.agent = VoiceAgent(self.agent_settings, self.api_settings)
        self.api = VoiceApiServer(self, self.api_settings)
        self._started = False
        self._api_started = False

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
                self._api_started = True
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
            self._api_started = False
            logger.exception("VOICE_API stop failed")

    # ------------------------------------------------------------------
    # 热重载
    # ------------------------------------------------------------------

    async def reload_settings(self) -> dict[str, Any]:
        """重新读 config.py，把变化**真正应用**到运行中的对象上。

        过去 WebUI 保存只改了 config 模块的 dict，VoiceRuntime 里的 dataclass
        快照（agent.settings / backend.settings 与它是同一个对象）永不刷新，
        于是「保存成功但没生效、必须重启」。这里就地写回并重建派生对象。

        返回 ``{"changed", "api_changed", "notes", "restart_keys"}``。
        """
        fresh_agent, fresh_api = load_voice_agent_settings()

        # 就地写回：runtime.agent_settings / agent.settings / backend.settings 同一对象
        changed = apply_settings(self.agent_settings, fresh_agent)

        # 独立端口的 host/port 不能热改（socket 已绑定），只同步其余字段
        api_changed: list[str] = []
        for key in ("enabled", "token"):
            new = getattr(fresh_api, key)
            if getattr(self.api_settings, key) != new:
                setattr(self.api_settings, key, new)
                api_changed.append(key)
        restart_keys = [
            key for key in _API_RESTART_KEYS
            if getattr(self.api_settings, key) != getattr(fresh_api, key)
        ]

        notes: list[str] = []
        try:
            notes.extend(await self.agent.refresh(changed))
        except Exception as exc:
            logger.exception("voice agent refresh failed")
            notes.append(f"语音配置应用失败：{exc}")

        # 语音总开关的热切换
        if "enabled" in changed:
            try:
                if self.agent_settings.enabled and not self.agent.running:
                    await self.agent.start()
                    notes.append("语音对话已启用")
                elif not self.agent_settings.enabled and self.agent.running:
                    await self.agent.stop()
                    notes.append("语音对话已停用")
            except Exception as exc:
                logger.exception("voice agent toggle failed")
                notes.append(f"语音总开关切换失败：{exc}")

        # 独立端口开关的热切换
        if "enabled" in api_changed and self._started:
            try:
                if self.api_settings.enabled and not self._api_started:
                    await self.api.start()
                    self._api_started = True
                    notes.append("独立语音端口已启动")
                elif not self.api_settings.enabled and self._api_started:
                    await self.api.stop()
                    self._api_started = False
                    notes.append("独立语音端口已停止")
            except Exception as exc:
                logger.exception("VOICE_API toggle failed")
                notes.append(f"独立语音端口切换失败：{exc}")

        if restart_keys:
            notes.append("独立语音端口的监听地址/端口需重启才能生效")

        return {
            "changed": changed,
            "api_changed": api_changed,
            "notes": notes,
            "restart_keys": restart_keys,
        }


_runtime: VoiceRuntime | None = None


def get_voice_runtime() -> VoiceRuntime:
    global _runtime
    if _runtime is None:
        _runtime = VoiceRuntime()
    return _runtime
