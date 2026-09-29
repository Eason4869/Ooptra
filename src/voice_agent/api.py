"""VOICE_API：供 AstrBot 插件 / 控制台调用的本地 HTTP。

本模块**只负责监听与鉴权**，路由实现全部来自 ``webui.voice_routes``——
3090（WebUI）与 3091（本端口）必须是同一套 handler，否则会像过去那样分叉：
3091 曾经自带一份手写路由，缺 ``/voice/channels``、``/voice/members`` 还会 500。

持有 ``VoiceRuntime`` 而不是 ``agent``：handler 每次请求重新读
``runtime.agent``，热重载替换 agent 后无需重启端口。
"""

from __future__ import annotations

import logging

from aiohttp import web

from voice_agent.settings import VoiceApiSettings
from webui.voice_routes import build_voice_routes

logger = logging.getLogger(__name__)


class VoiceApiServer:
    def __init__(self, runtime, settings: VoiceApiSettings) -> None:
        self.runtime = runtime
        self.settings = settings
        self._runner: web.AppRunner | None = None

    def _authed(self, request: web.Request) -> bool:
        token = (self.settings.token or "").strip()
        if not token:
            return True
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer ") and header[7:].strip() == token:
            return True
        if request.query.get("token", "") == token:
            return True
        return request.headers.get("X-Ooptra-Token", "") == token

    def _err(self, message: str, status: int = 400) -> web.Response:
        return web.json_response({"ok": False, "error": message}, status=status)

    async def _guard(self, request: web.Request, handler) -> web.Response:
        if not self._authed(request):
            return self._err("访问令牌无效", 401)
        try:
            return await handler(request)
        except Exception as exc:
            logger.exception("voice api handler failed")
            return self._err(str(exc), 500)

    def _wrap(self, handler):
        """把 handler 包成带鉴权与异常兜底的 aiohttp handler。"""

        async def wrapped(request: web.Request) -> web.Response:
            return await self._guard(request, handler)

        return wrapped

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.settings.enabled:
            logger.info("voice api disabled")
            return
        app = web.Application()
        app.add_routes(build_voice_routes(self.runtime, wrap=self._wrap))
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.settings.host, self.settings.port)
        await site.start()
        self._runner = runner
        if not (self.settings.token or "").strip():
            logger.warning(
                "VOICE_API on %s:%s has NO token configured — anyone who can reach "
                "this port can control the voice channel",
                self.settings.host,
                self.settings.port,
            )
        logger.info(
            "VOICE_API listening on http://%s:%s",
            self.settings.host,
            self.settings.port,
        )

    async def stop(self) -> None:
        runner = self._runner
        self._runner = None
        if runner is not None:
            await runner.cleanup()
