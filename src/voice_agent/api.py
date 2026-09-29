"""VOICE_API：供 AstrBot 插件 / 控制台调用的本地 HTTP。"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from voice_agent.settings import VoiceApiSettings

logger = logging.getLogger(__name__)


class VoiceApiServer:
    def __init__(self, agent, settings: VoiceApiSettings) -> None:
        self.agent = agent
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

    def _ok(self, payload: dict[str, Any] | None = None) -> web.Response:
        data = {"ok": True}
        if payload:
            data.update(payload)
        return web.json_response(data)

    async def _guard(self, request: web.Request, handler) -> web.Response:
        if not self._authed(request):
            return self._err("unauthorized", 401)
        try:
            return await handler(request)
        except Exception as exc:
            logger.exception("voice api handler failed")
            return self._err(str(exc), 500)

    # ------------------------------------------------------------------
    # handlers
    # ------------------------------------------------------------------

    async def handle_status(self, request: web.Request) -> web.Response:
        return self._ok({"status": self.agent.status()})

    async def handle_join(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        area = str(body.get("area") or request.query.get("area") or "")
        channel = str(body.get("channel") or request.query.get("channel") or "")
        result = await self.agent.join(area, channel)
        return self._ok(result)

    async def handle_leave(self, request: web.Request) -> web.Response:
        result = await self.agent.leave()
        return self._ok(result)

    async def handle_members(self, request: web.Request) -> web.Response:
        bot = self.agent._bot
        if bot is None:
            return self._err("bot not ready", 503)
        area = str(request.query.get("area") or self.agent._area or "")
        if not area:
            return self._err("area required")
        members = await bot.channels.get_voice_channel_members(area=area)
        # SDK 返回结构可能是 list 或 dict，尽量归一
        items: list[dict[str, Any]] = []
        raw_list = members
        if isinstance(members, dict):
            raw_list = members.get("members") or members.get("list") or []
        if isinstance(raw_list, list):
            for row in raw_list:
                if not isinstance(row, dict):
                    continue
                items.append(
                    {
                        "uid": str(row.get("uid") or row.get("pid") or row.get("person_uid") or ""),
                        "name": str(row.get("name") or row.get("nickname") or ""),
                        "mic_muted": bool(row.get("mic_muted") or row.get("m") or False),
                        "speaker_muted": bool(row.get("speaker_muted") or row.get("hm") or False),
                        "raw": row,
                    }
                )
        return self._ok({"area": area, "count": len(items), "members": items, "raw": members})

    async def handle_persona_get(self, request: web.Request) -> web.Response:
        return self._ok({"persona": self.agent.settings.persona})

    async def handle_persona_put(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        persona = body.get("persona")
        if not isinstance(persona, str) or not persona.strip():
            return self._err("persona required")
        self.agent.update_persona(persona)
        return self._ok({"persona": self.agent.settings.persona})

    async def handle_memory_get(self, request: web.Request) -> web.Response:
        user_key = request.query.get("user_key", "")
        limit = request.query.get("limit")
        limit_i = int(limit) if limit and str(limit).isdigit() else None
        messages = self.agent.memory.as_messages(user_key=user_key, limit=limit_i)
        return self._ok({"messages": messages, "user_key": user_key})

    async def handle_memory_post(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        role = str(body.get("role") or "user")
        content = str(body.get("content") or "")
        if role not in {"user", "assistant", "system"}:
            return self._err("invalid role")
        if not content.strip():
            return self._err("content required")
        row = self.agent.memory.append(
            role,
            content,
            user_key=str(body.get("user_key") or ""),
            channel_key=str(body.get("channel_key") or ""),
        )
        return self._ok({"turn": row})

    async def handle_memory_delete(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        removed = self.agent.memory.clear(user_key=str(body.get("user_key") or ""))
        return self._ok({"removed": removed})

    async def handle_speak(self, request: web.Request) -> web.Response:
        body = await self._json(request)
        text = str(body.get("text") or "")
        result = await self.agent.speak_text(text)
        if not result.get("ok"):
            return self._err(str(result.get("error") or "speak failed"), 400)
        return self._ok(result)

    @staticmethod
    async def _json(request: web.Request) -> dict[str, Any]:
        if not request.can_read_body:
            return {}
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.settings.enabled:
            logger.info("voice api disabled")
            return
        app = web.Application()
        routes = [
            web.get("/health", lambda r: self._guard(r, self.handle_status)),
            web.get("/voice/status", lambda r: self._guard(r, self.handle_status)),
            web.post("/voice/join", lambda r: self._guard(r, self.handle_join)),
            web.post("/voice/leave", lambda r: self._guard(r, self.handle_leave)),
            web.get("/voice/members", lambda r: self._guard(r, self.handle_members)),
            web.get("/persona", lambda r: self._guard(r, self.handle_persona_get)),
            web.put("/persona", lambda r: self._guard(r, self.handle_persona_put)),
            web.get("/memory", lambda r: self._guard(r, self.handle_memory_get)),
            web.post("/memory", lambda r: self._guard(r, self.handle_memory_post)),
            web.delete("/memory", lambda r: self._guard(r, self.handle_memory_delete)),
            web.post("/voice/speak", lambda r: self._guard(r, self.handle_speak)),
        ]
        app.add_routes(routes)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.settings.host, self.settings.port)
        await site.start()
        self._runner = runner
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
