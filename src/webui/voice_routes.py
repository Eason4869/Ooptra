"""Ooptra VOICE_API —— 与 astrbot_plugin_ooptra 契约对齐。

插件契约（默认 api_base=http://127.0.0.1:3090，无 /api 前缀）：

    GET  /health
    GET  /voice/status
    GET  /voice/members?area=&channel=
    POST /voice/join    {"area","channel"}
    POST /voice/leave
    Authorization: Bearer <token>   # 可选

响应形态（扁平，插件 format_status / format_members 直接读）：

    status:  {ok, joined, area, channel, state, ...}
    members: {ok, count, members:[{uid,name,mic,speaker,m,hm}], area, channel}
             mic/speaker: true=开，false=闭
             m/hm:        1=闭麦/闭听，0=正常

同时保留 /api/voice|persona|memory 别名，供 Web 控制台使用。
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


def mount_voice_routes(app: web.Application, voice_runtime: Any) -> None:
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

    # ── 插件契约：扁平 status ──
    def status_payload() -> dict[str, Any]:
        st = agent.status() or {}
        joined = bool(st.get("joined"))
        state = "joined" if joined else "idle"
        if st.get("speaking"):
            state = "playing"
        return {
            "joined": joined,
            "area": st.get("area") or "",
            "channel": st.get("channel") or "",
            "state": state,
            "backend": st.get("backend") or "",
            "mode": st.get("mode") or "",
            "enabled": bool(st.get("enabled")),
            "turns": int(st.get("turns") or 0),
            "last_reply": st.get("last_reply") or "",
            "last_user_text": st.get("last_user_text") or "",
            # WebUI 兼容
            "status": st,
        }

    async def health(_request: web.Request) -> web.Response:
        return ok({"service": "ooptra-voice-api", "enabled": bool(agent.settings.enabled)})

    async def voice_status(_request: web.Request) -> web.Response:
        return ok(status_payload())

    async def voice_join(request: web.Request) -> web.Response:
        body = await read_json(request)
        area = str(body.get("area") or request.query.get("area") or "")
        channel = str(body.get("channel") or request.query.get("channel") or "")
        result = await agent.join(area, channel)
        return ok(
            {
                "joined": True,
                "area": result.get("area") or area,
                "channel": result.get("channel") or channel,
                "mode": result.get("mode") or "",
            }
        )

    async def voice_leave(_request: web.Request) -> web.Response:
        await agent.leave()
        return ok({"joined": False})

    async def voice_members(request: web.Request) -> web.Response:
        bot = agent._bot
        if bot is None:
            return err("Oopz bot 尚未就绪", 503)
        area = str(request.query.get("area") or agent._area or "")
        if not area:
            return err("缺少 area 参数")
        members_raw = await bot.channels.get_voice_channel_members(area=area)

        items: list[dict[str, Any]] = []
        raw_list = members_raw
        if isinstance(members_raw, dict):
            raw_list = (
                members_raw.get("members")
                or members_raw.get("list")
                or members_raw.get("data")
                or []
            )
        # VoiceChannelMembersResult 可能是对象
        if not isinstance(raw_list, list):
            raw_list = getattr(members_raw, "members", None) or []

        for row in raw_list or []:
            if not isinstance(row, dict):
                # pydantic 模型
                row = {
                    "uid": getattr(row, "uid", "") or getattr(row, "pid", ""),
                    "name": getattr(row, "name", "") or getattr(row, "nickname", ""),
                    "mic_muted": bool(getattr(row, "mic_muted", False) or getattr(row, "m", 0)),
                    "speaker_muted": bool(
                        getattr(row, "speaker_muted", False) or getattr(row, "hm", 0)
                    ),
                }
            uid = str(
                row.get("uid")
                or row.get("pid")
                or row.get("person_uid")
                or row.get("user_id")
                or ""
            )
            name = str(row.get("name") or row.get("nickname") or row.get("user_name") or "")

            # m/hm：1=闭，0=开
            if "m" in row:
                mic_muted = bool(int(row.get("m") or 0) == 1)
            elif "mic_muted" in row:
                mic_muted = bool(row.get("mic_muted"))
            elif "mic" in row:
                # mic: true=开
                mic_muted = not bool(row.get("mic"))
            else:
                mic_muted = False

            if "hm" in row:
                sp_muted = bool(int(row.get("hm") or 0) == 1)
            elif "speaker_muted" in row:
                sp_muted = bool(row.get("speaker_muted"))
            elif "speaker" in row:
                sp_muted = not bool(row.get("speaker"))
            else:
                sp_muted = False

            items.append(
                {
                    "uid": uid,
                    "name": name,
                    # 插件首选 mic/speaker（true=开）
                    "mic": (not mic_muted),
                    "speaker": (not sp_muted),
                    # 兼容 Oopz 标志（1=闭）
                    "m": 1 if mic_muted else 0,
                    "hm": 1 if sp_muted else 0,
                }
            )

        return ok(
            {
                "count": len(items),
                "members": items,
                "area": area,
                "channel": request.query.get("channel") or agent._channel or "",
            }
        )

    async def voice_speak(request: web.Request) -> web.Response:
        body = await read_json(request)
        result = await agent.speak_text(str(body.get("text") or ""))
        if not result.get("ok"):
            return err(str(result.get("error") or "speak failed"))
        return ok(result)

    # ── 域/频道（WebUI 用）──
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

    # ── 人格 / 记忆 ──
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

    # ── 路由：插件契约 + /api 别名 ──
    pairs = [
        ("GET", "/health", health),
        ("GET", "/voice/status", voice_status),
        ("GET", "/voice/members", voice_members),
        ("POST", "/voice/join", voice_join),
        ("POST", "/voice/leave", voice_leave),
        ("POST", "/voice/speak", voice_speak),
        ("GET", "/oopz/areas", oopz_areas),
        ("GET", "/oopz/channels", oopz_channels),
        ("GET", "/persona", persona_get),
        ("PUT", "/persona", persona_put),
        ("GET", "/memory", memory_get),
        ("POST", "/memory", memory_post),
        ("DELETE", "/memory", memory_delete),
    ]
    routes = []
    for method, path, handler in pairs:
        routes.append(web.route(method, path, handler))
        # WebUI 历史路径 /api/*
        routes.append(web.route(method, "/api" + path, handler))
    app.add_routes(routes)
    logger.debug("voice routes mounted (plugin contract + /api aliases)")
