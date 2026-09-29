"""将 Voice API 挂到 WebUI 控制台（同端口 3090，同一套 token）。"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


def mount_voice_routes(app: web.Application, voice_runtime: Any) -> None:
    """在已有 WebUI Application 上注册 /api/voice|persona|memory。"""
    agent = voice_runtime.agent

    def ok(payload: dict[str, Any] | None = None) -> web.Response:
        data: dict[str, Any] = {"ok": True}
        if payload:
            data.update(payload)
        return web.json_response(data)

    def err(message: str, status: int = 400) -> web.Response:
        return web.json_response({"ok": False, "error": message}, status=status)

    async def read_json(request: web.Request) -> dict[str, Any]:
        if not request.can_read_body:
            return {}
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def voice_status(_request: web.Request) -> web.Response:
        return ok({"status": agent.status()})

    async def voice_join(request: web.Request) -> web.Response:
        body = await read_json(request)
        area = str(body.get("area") or request.query.get("area") or "")
        channel = str(body.get("channel") or request.query.get("channel") or "")
        result = await agent.join(area, channel)
        return ok(result)

    async def voice_leave(_request: web.Request) -> web.Response:
        return ok(await agent.leave())

    async def voice_members(request: web.Request) -> web.Response:
        bot = agent._bot
        if bot is None:
            return err("Oopz bot 尚未就绪", 503)
        area = str(request.query.get("area") or agent._area or "")
        if not area:
            return err("缺少 area 参数")
        members = await bot.channels.get_voice_channel_members(area=area)
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
                        "mic_muted": bool(row.get("mic_muted") or row.get("m")),
                        "speaker_muted": bool(row.get("speaker_muted") or row.get("hm")),
                    }
                )
        return ok({"area": area, "count": len(items), "members": items})

    async def voice_speak(request: web.Request) -> web.Response:
        body = await read_json(request)
        result = await agent.speak_text(str(body.get("text") or ""))
        if not result.get("ok"):
            return err(str(result.get("error") or "speak failed"))
        return ok(result)

    async def oopz_areas(_request: web.Request) -> web.Response:
        bot = agent._bot
        if bot is None:
            return err("Oopz bot 尚未就绪", 503)
        areas = await bot.areas.get_joined_areas()
        items = []
        for row in areas or []:
            items.append(
                {
                    "id": str(getattr(row, "area_id", "") or getattr(row, "id", "") or ""),
                    "name": str(getattr(row, "name", "") or ""),
                }
            )
        # 附带当前默认，方便前端预选
        try:
            import config as runtime_config

            default_area = str(runtime_config.OOPZ_CONFIG.get("default_area") or "")
            default_channel = str(runtime_config.OOPZ_CONFIG.get("default_channel") or "")
        except Exception:
            default_area = agent.settings.area
            default_channel = agent.settings.channel
        return ok(
            {
                "areas": items,
                "default_area": default_area or agent._area,
                "default_channel": default_channel or agent._channel,
            }
        )

    async def oopz_channels(request: web.Request) -> web.Response:
        bot = agent._bot
        if bot is None:
            return err("Oopz bot 尚未就绪", 503)
        area = str(request.query.get("area") or "").strip()
        if not area:
            return err("缺少 area 参数")
        groups = await bot.areas.get_area_channels(area)
        channels: list[dict[str, Any]] = []
        for group in groups or []:
            for ch in getattr(group, "channels", None) or []:
                ctype = str(getattr(ch, "channel_type", "") or "").upper()
                if ctype and ctype not in {"VOICE", "AUDIO"}:
                    continue
                channels.append(
                    {
                        "id": str(getattr(ch, "channel_id", "") or getattr(ch, "id", "") or ""),
                        "name": str(getattr(ch, "name", "") or ""),
                        "type": ctype or "VOICE",
                    }
                )
        return ok({"area": area, "channels": channels})

    async def persona_get(_request: web.Request) -> web.Response:
        return ok({"persona": agent.settings.persona})

    async def persona_put(request: web.Request) -> web.Response:
        body = await read_json(request)
        persona = body.get("persona")
        if not isinstance(persona, str) or not persona.strip():
            return err("persona 不能为空")
        agent.update_persona(persona)
        return ok({"persona": agent.settings.persona})

    async def memory_get(request: web.Request) -> web.Response:
        user_key = request.query.get("user_key", "")
        limit_raw = request.query.get("limit")
        limit = int(limit_raw) if limit_raw and str(limit_raw).isdigit() else None
        return ok(
            {
                "messages": agent.memory.as_messages(user_key=user_key, limit=limit),
                "persona": agent.settings.persona,
            }
        )

    async def memory_post(request: web.Request) -> web.Response:
        body = await read_json(request)
        role = str(body.get("role") or "user")
        content = str(body.get("content") or "")
        if role not in {"user", "assistant", "system"}:
            return err("role 无效")
        if not content.strip():
            return err("content 不能为空")
        row = agent.memory.append(
            role,
            content,
            user_key=str(body.get("user_key") or ""),
            channel_key=str(body.get("channel_key") or ""),
        )
        return ok({"turn": row})

    async def memory_delete(request: web.Request) -> web.Response:
        body = await read_json(request)
        removed = agent.memory.clear(user_key=str(body.get("user_key") or ""))
        return ok({"removed": removed})

    app.add_routes(
        [
            web.get("/api/voice/status", voice_status),
            web.post("/api/voice/join", voice_join),
            web.post("/api/voice/leave", voice_leave),
            web.get("/api/voice/members", voice_members),
            web.post("/api/voice/speak", voice_speak),
            web.get("/api/oopz/areas", oopz_areas),
            web.get("/api/oopz/channels", oopz_channels),
            web.get("/api/persona", persona_get),
            web.put("/api/persona", persona_put),
            web.get("/api/memory", memory_get),
            web.post("/api/memory", memory_post),
            web.delete("/api/memory", memory_delete),
        ]
    )
    logger.debug("voice routes mounted on webui")
