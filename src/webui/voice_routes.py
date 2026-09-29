"""Ooptra VOICE_API —— 与 astrbot_plugin_ooptra 契约对齐。

插件契约（默认 api_base=http://127.0.0.1:3090，无 /api 前缀）：

    GET  /health
    GET  /voice/status
    GET  /voice/members?area=&channel=
    GET  /voice/channels?area=
    POST /voice/join    {"area","channel"}
    POST /voice/leave
    POST /voice/speak   {"text"}
    Authorization: Bearer <token>   # 可选

本模块是语音 HTTP 契约的**唯一实现**，两个入口共用：

  * WebUI（3090）—— ``mount_voice_routes``，额外挂 /api/* 历史别名
  * 独立 VOICE_API 端口（3091）—— ``build_voice_routes``，见 voice_agent/api.py

不要在任何地方另写一份 handler：3091 曾经自带一套手写路由，结果与 3090 分叉
（缺 ``/voice/channels``、``/voice/members`` 因 pydantic 模型不可序列化而 500）。

响应形态（扁平，插件 format_status / format_members 直接读）：

    status:  {ok, joined, area, channel, state, ...}
    members: {ok, count, members:[{uid,name,mic,speaker,m,hm,mic_muted,speaker_muted}],
              area, channel, channel_counts}
             mic/speaker: true=开，false=闭，null=未知
             m/hm:        1=闭麦/闭听，0=正常，null=未知
             mic_muted/speaker_muted: true=闭，false=开，null=未知（WebUI 读这两个）
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)

# 昵称补全的超时：宁可显示短 ID，也不让 /voice/members 卡住
_NAME_TIMEOUT = 3.0


# ----------------------------------------------------------------------
# 成员归一
# ----------------------------------------------------------------------


def _field(row: Any, *names: str, default: Any = None) -> Any:
    """从 pydantic 模型或原始 dict 里按候选字段名取值，取不到返回 default。"""
    for name in names:
        value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
        if value is not None:
            return value
    return default


def _muted(row: Any, muted_key: str, flag_key: str, state_key: str) -> bool | None:
    """归一静音状态。返回 True=已闭，False=开，None=未知（不猜）。"""
    muted = _field(row, muted_key)
    if muted is not None:
        return bool(muted)
    flag = _field(row, flag_key)  # m / hm：1=闭，0=开
    if flag is not None:
        try:
            return int(flag) == 1
        except (TypeError, ValueError):
            pass
    state = _field(row, state_key)  # mic / speaker：true=开
    if state is not None:
        return not bool(state)
    return None


def normalize_member(row: Any, name: str = "") -> dict[str, Any]:
    """把 SDK 模型或原始 dict 归一成插件与 WebUI 都能读的成员结构。

    ``mic``/``speaker``/``m``/``hm`` 给插件读，``mic_muted``/``speaker_muted``
    给 WebUI 读；Oopz 的 membersByChannels 不返回静音状态，取不到时一律为
    ``None``（未知），不伪造成「开麦」。
    """
    uid = str(_field(row, "uid", "pid", "person_uid", "user_id", default="") or "")
    resolved = name or str(_field(row, "name", "nickname", "user_name", default="") or "")
    mic_muted = _muted(row, "mic_muted", "m", "mic")
    sp_muted = _muted(row, "speaker_muted", "hm", "speaker")
    return {
        "uid": uid,
        "name": resolved,
        # 插件首选 mic/speaker（true=开）
        "mic": None if mic_muted is None else (not mic_muted),
        "speaker": None if sp_muted is None else (not sp_muted),
        # 兼容 Oopz 标志（1=闭）
        "m": None if mic_muted is None else (1 if mic_muted else 0),
        "hm": None if sp_muted is None else (1 if sp_muted else 0),
        # WebUI 读这两个
        "mic_muted": mic_muted,
        "speaker_muted": sp_muted,
        "is_bot": bool(_field(row, "is_bot", "isBot", default=False) or False),
    }


async def _member_names(uids: list[str]) -> dict[str, str]:
    """批量补全昵称，失败/超时则回退 NameResolver 的短 ID。"""
    unique = [uid for uid in dict.fromkeys(uids) if uid]
    if not unique:
        return {}
    try:
        from oopz.name_resolver import get_resolver

        resolver = get_resolver()
    except Exception:
        logger.debug("name resolver unavailable", exc_info=True)
        return {}
    try:
        await asyncio.wait_for(resolver.ensure_users(unique), timeout=_NAME_TIMEOUT)
    except Exception as exc:
        logger.debug("resolve member names failed: %s", exc)
    names: dict[str, str] = {}
    for uid in unique:
        try:
            names[uid] = resolver.user_cached(uid)
        except Exception:
            names[uid] = ""
    return names


def _channel_member_map(members_raw: Any) -> dict[str, list[Any]]:
    """把 get_voice_channel_members 结果归一成 {channel_id: [member, ...]}。"""
    if members_raw is None:
        return {}
    grouped = getattr(members_raw, "channel_members", None)
    if isinstance(grouped, dict):
        return {str(k): list(v or []) for k, v in grouped.items()}
    if isinstance(members_raw, dict):
        src = members_raw.get("channelMembers") or members_raw.get("channel_members")
        if isinstance(src, dict):
            return {str(k): list(v or []) for k, v in src.items()}
    return {}


def _default_target() -> tuple[str, str]:
    """读取 OOPZ_CONFIG 里「设为默认」的域/频道。"""
    try:
        import config as runtime_config

        return (
            str(runtime_config.OOPZ_CONFIG.get("default_area") or ""),
            str(runtime_config.OOPZ_CONFIG.get("default_channel") or ""),
        )
    except Exception:
        return "", ""


# ----------------------------------------------------------------------
# 路由构造
# ----------------------------------------------------------------------


def build_voice_routes(
    voice_runtime: Any,
    *,
    with_api_alias: bool = False,
    wrap: Callable[[Any], Any] | None = None,
) -> list[Any]:
    """构造语音契约路由。

    ``voice_runtime`` 需提供 ``.agent``；handler 在**每次请求时**重新读取
    ``voice_runtime.agent``，这样热重载替换 agent 后无需重新挂载路由。

    ``wrap`` 用于包一层鉴权/异常兜底（独立 VOICE_API 端口用）。
    """

    def current_agent() -> Any:
        return voice_runtime.agent

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
    def status_payload(agent: Any) -> dict[str, Any]:
        st = agent.status() or {}
        joined = bool(st.get("joined"))
        state = "joined" if joined else "idle"
        if st.get("speaking"):
            state = "playing"
        default_area, default_channel = _default_target()
        if not default_area and not default_channel:
            default_area = agent.settings.area
            default_channel = agent.settings.channel
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
            # 插件侧默认目标（WebUI「设为默认」写入 OOPZ_CONFIG）
            "default_area": default_area or agent._area or "",
            "default_channel": default_channel or agent._channel or "",
            # WebUI 兼容
            "status": st,
        }

    async def health(_request: web.Request) -> web.Response:
        agent = current_agent()
        return ok(
            {
                "service": "ooptra-voice-api",
                "version": _ooptra_version(),
                "enabled": bool(agent.settings.enabled),
            }
        )

    async def voice_status(_request: web.Request) -> web.Response:
        return ok(status_payload(current_agent()))

    async def voice_join(request: web.Request) -> web.Response:
        agent = current_agent()
        body = await read_json(request)
        area = str(body.get("area") or request.query.get("area") or "")
        channel = str(body.get("channel") or request.query.get("channel") or "")
        try:
            result = await agent.join(area, channel)
        except Exception as exc:
            logger.warning("voice join failed: %s", exc)
            return err(str(exc) or "进语音失败", 503)
        return ok(
            {
                "joined": True,
                "area": result.get("area") or area,
                "channel": result.get("channel") or channel,
                "mode": result.get("mode") or "",
            }
        )

    async def voice_leave(_request: web.Request) -> web.Response:
        agent = current_agent()
        try:
            await agent.leave()
        except Exception as exc:
            logger.warning("voice leave failed: %s", exc)
            return err(str(exc) or "退语音失败", 503)
        return ok({"joined": False})

    async def voice_members(request: web.Request) -> web.Response:
        agent = current_agent()
        bot = agent._bot
        if bot is None:
            return err("Oopz bot 尚未就绪", 503)
        area = str(request.query.get("area") or agent._area or "")
        if not area:
            return err("缺少 area 参数")
        channel = str(request.query.get("channel") or "").strip()
        try:
            members_raw = await bot.channels.get_voice_channel_members(area=area)
        except Exception as exc:
            logger.warning("get voice members failed: %s", exc)
            return err(f"获取语音成员失败：{exc}", 502)

        grouped = _channel_member_map(members_raw)
        if channel:
            raw_list = grouped.get(channel, [])
        else:
            # 未指定频道时汇总整个域；同时回传分频道人数
            raw_list = [m for rows in grouped.values() for m in rows]

        rows = [row for row in (raw_list or []) if row is not None]
        names = await _member_names(
            [str(_field(row, "uid", "pid", "person_uid", "user_id", default="") or "") for row in rows]
        )
        items = [
            normalize_member(row, names.get(str(_field(row, "uid", default="") or ""), ""))
            for row in rows
        ]

        return ok(
            {
                "count": len(items),
                "members": items,
                "area": area,
                "channel": channel or agent._channel or "",
                "channel_counts": {
                    cid: len(
                        [
                            m
                            for m in rows_in_channel
                            if not bool(
                                _field(m, "is_bot", "isBot", default=False) or False
                            )
                        ]
                    )
                    for cid, rows_in_channel in grouped.items()
                },
            }
        )

    async def voice_channels(request: web.Request) -> web.Response:
        """列出域内语音频道及在线人数，供插件按域汇总、按名字找频道。"""
        agent = current_agent()
        bot = agent._bot
        if bot is None:
            return err("Oopz bot 尚未就绪", 503)
        area = str(request.query.get("area") or agent._area or "").strip()
        if not area:
            return err("缺少 area 参数")

        names: dict[str, str] = {}
        try:
            groups = await bot.areas.get_area_channels(area)
            for group in groups or []:
                for ch in getattr(group, "channels", None) or []:
                    ctype = str(getattr(ch, "channel_type", "") or "").upper()
                    if ctype and ctype not in {"VOICE", "AUDIO"}:
                        continue
                    cid = str(getattr(ch, "channel_id", "") or getattr(ch, "id", "") or "")
                    if not cid:
                        continue
                    names[cid] = str(getattr(ch, "name", "") or "")
        except Exception as exc:
            logger.warning("list area channels failed: %s", exc)

        counts: dict[str, int] = {}
        try:
            members_raw = await bot.channels.get_voice_channel_members(area=area)
            for cid, members in _channel_member_map(members_raw).items():
                counts[cid] = len(
                    [
                        m
                        for m in members
                        if not bool(_field(m, "is_bot", "isBot", default=False) or False)
                    ]
                )
        except Exception as exc:
            logger.warning("count voice members failed: %s", exc)

        channels = [
            {"id": cid, "name": names.get(cid) or cid, "count": int(counts.get(cid) or 0)}
            for cid in sorted(
                set(names) | set(counts),
                key=lambda x: (-counts.get(x, 0), names.get(x) or x),
            )
        ]
        default_area, default_channel = _default_target()
        return ok(
            {
                "area": area,
                "channels": channels,
                "default_area": default_area or agent._area or "",
                "default_channel": default_channel or agent._channel or "",
            }
        )

    async def voice_speak(request: web.Request) -> web.Response:
        agent = current_agent()
        body = await read_json(request)
        text = str(body.get("text") or "")
        try:
            result = await agent.speak_text(text)
        except Exception as exc:
            logger.warning("voice speak failed: %s", exc)
            return err(str(exc) or "speak failed", 502)
        if not result.get("ok"):
            return err(str(result.get("error") or "speak failed"))
        return ok(result)

    # ── 域/频道（WebUI 用）──
    async def oopz_areas(_request: web.Request) -> web.Response:
        agent = current_agent()
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
        default_area, default_channel = _default_target()
        return ok(
            {
                "areas": items,
                "default_area": default_area or agent._area,
                "default_channel": default_channel or agent._channel,
            }
        )

    async def oopz_channels(request: web.Request) -> web.Response:
        agent = current_agent()
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
        return ok({"persona": current_agent().settings.persona})

    async def persona_put(request: web.Request) -> web.Response:
        agent = current_agent()
        body = await read_json(request)
        persona = body.get("persona")
        if not isinstance(persona, str) or not persona.strip():
            return err("persona 不能为空")
        agent.update_persona(persona)
        return ok({"persona": agent.settings.persona})

    async def memory_get(request: web.Request) -> web.Response:
        agent = current_agent()
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
        agent = current_agent()
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
        agent = current_agent()
        body = await read_json(request)
        removed = agent.memory.clear(user_key=str(body.get("user_key") or ""))
        return ok({"removed": removed})

    # ── 路由：插件契约 + /api 别名 ──
    pairs = [
        ("GET", "/health", health),
        ("GET", "/voice/status", voice_status),
        ("GET", "/voice/members", voice_members),
        ("GET", "/voice/channels", voice_channels),
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
    routes: list[Any] = []
    for method, path, handler in pairs:
        if wrap is not None:
            handler = wrap(handler)
        routes.append(web.route(method, path, handler))
        if with_api_alias:
            # WebUI 历史路径 /api/*
            routes.append(web.route(method, "/api" + path, handler))
    return routes


def _ooptra_version() -> str:
    try:
        from core.version import __version__

        return str(__version__)
    except Exception:
        return ""


def mount_voice_routes(app: web.Application, voice_runtime: Any) -> None:
    """挂到 WebUI app 上：插件契约路径 + /api/* 历史别名。"""
    routes = build_voice_routes(voice_runtime, with_api_alias=True)
    app.add_routes(routes)
    logger.debug("voice routes mounted (%d routes, plugin contract + /api aliases)", len(routes))
