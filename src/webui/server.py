"""Ooptra Web 控制台：状态、日志、配置与 Oopz 登录。

只依赖 aiohttp（桥接本身已有依赖），默认绑定 127.0.0.1:3090。
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import platform
import sys
from typing import Any

from aiohttp import web

import config as runtime_config
from core.logger_config import get_logger
from core.paths import LOGS_DIR, PROJECT_ROOT
from core.version import __version__
from webui import config_editor
from webui.log_tail import LogTailer
from webui.oopz_login import OopzLoginService, credentials_summary

logger = get_logger("WebUI")

COOKIE_NAME = "oopz_webui_token"
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3090
DEFAULT_LOG_LINES = 300


def _is_loopback(host: str) -> bool:
    text = str(host or "").strip().lower()
    if text in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


class WebUIConsole:
    """控制台生命周期与 HTTP 接口。"""

    def __init__(
        self,
        state: Any,
        controller: Any,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._state = state
        self._controller = controller
        self._config = config if isinstance(config, dict) else getattr(runtime_config, "WEBUI_CONFIG", {}) or {}
        self._tailer = LogTailer(LOGS_DIR)
        self._login = OopzLoginService(controller, state)
        self._token = ""
        self._host = DEFAULT_HOST
        self._port = DEFAULT_PORT
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def start(self) -> None:
        if not bool(self._config.get("enabled", True)):
            logger.info("Web 控制台已按 config.py 的 WEBUI_CONFIG.enabled 禁用")
            return

        self._host = str(self._config.get("host") or DEFAULT_HOST).strip() or DEFAULT_HOST
        self._port = int(self._config.get("port") or DEFAULT_PORT)
        self._token = str(self._config.get("token") or "").strip()

        if not self._token and not _is_loopback(self._host):
            logger.warning(
                "Web 控制台绑定在 %s 且 token 为空：局域网内任何人都能打开，请自行确认网络环境",
                self._host,
            )

        app = web.Application(middlewares=[self._auth_middleware])
        app.add_routes(
            [
                web.get("/", self._handle_index),
                web.get("/favicon.ico", self._handle_favicon),
                web.get("/assets/{name}", self._handle_asset),
                web.get("/api/status", self._handle_status),
                web.get("/api/credentials", self._handle_credentials),
                web.get("/api/logs", self._handle_logs_list),
                web.get("/api/logs/tail", self._handle_logs_tail),
                web.get("/api/logs/stream", self._handle_logs_stream),
                web.get("/api/config", self._handle_config_get),
                web.post("/api/config", self._handle_config_post),
                web.get("/api/login/browser", self._handle_browser_login_status),
                web.post("/api/login/browser", self._handle_browser_login_start),
                web.post("/api/login/browser/cancel", self._handle_browser_login_cancel),
                web.post("/api/login/api", self._handle_api_login),
                web.post("/api/bridge/restart", self._handle_bridge_restart),
            ]
        )

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, host=self._host, port=self._port)
        try:
            await site.start()
        except OSError as exc:
            await runner.cleanup()
            logger.error(
                "Web 控制台启动失败（%s:%s）：%s；桥接不受影响，可修改 WEBUI_CONFIG.port 后重试",
                self._host,
                self._port,
                exc,
            )
            return

        self._runner = runner
        self._site = site
        suffix = "（已设置访问令牌，用 ?token=... 打开）" if self._token else ""
        logger.info("Web 控制台已启动：%s%s", self.base_url, suffix)

    async def stop(self) -> None:
        await self._login.shutdown()
        if self._runner is not None:
            with contextlib.suppress(Exception):
                await self._runner.cleanup()
        self._runner = None
        self._site = None

    # ------------------------------------------------------------------
    # 鉴权
    # ------------------------------------------------------------------

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        if not self._token or not request.path.startswith("/api/"):
            return await handler(request)

        provided = (
            request.query.get("token")
            or request.cookies.get(COOKIE_NAME)
            or str(request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        )
        if provided != self._token:
            return web.json_response({"ok": False, "error": "访问令牌无效"}, status=401)

        response = await handler(request)
        if request.query.get("token") and isinstance(response, web.Response):
            response.set_cookie(
                COOKIE_NAME,
                self._token,
                httponly=True,
                samesite="Lax",
                max_age=30 * 86400,
            )
        return response

    # ------------------------------------------------------------------
    # 静态资源
    # ------------------------------------------------------------------

    async def _handle_index(self, _request: web.Request) -> web.StreamResponse:
        return web.FileResponse(os.path.join(ASSETS_DIR, "index.html"), headers={"Cache-Control": "no-cache"})

    async def _handle_favicon(self, _request: web.Request) -> web.StreamResponse:
        return web.Response(status=204)

    async def _handle_asset(self, request: web.Request) -> web.StreamResponse:
        name = os.path.basename(str(request.match_info.get("name") or ""))
        path = os.path.join(ASSETS_DIR, name)
        if not name or not os.path.isfile(path):
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------------
    # 状态 / 凭据
    # ------------------------------------------------------------------

    async def _handle_status(self, _request: web.Request) -> web.StreamResponse:
        oopz_cfg = getattr(runtime_config, "OOPZ_CONFIG", {}) or {}
        onebot_cfg = getattr(runtime_config, "ONEBOT_V11_CONFIG", {}) or {}
        return web.json_response(
            {
                "ok": True,
                "bridge": self._controller.snapshot(),
                "process": {
                    "version": __version__,
                    "pid": os.getpid(),
                    "python": platform.python_version(),
                    "executable": sys.executable,
                    "platform": platform.platform(),
                    "project_root": PROJECT_ROOT,
                    "log_file": os.path.join(LOGS_DIR, "oopz_bot.log"),
                },
                "config": {
                    "webui": {
                        "host": self._host,
                        "port": self._port,
                        "token_required": bool(self._token),
                    },
                    "oopz": {
                        "default_area": str(oopz_cfg.get("default_area") or ""),
                        "default_channel": str(oopz_cfg.get("default_channel") or ""),
                        "proxy": str(oopz_cfg.get("proxy") or ""),
                    },
                    "onebot": {
                        "enabled": bool(onebot_cfg.get("enabled", False)),
                        "enable_ws_reverse": bool(onebot_cfg.get("enable_ws_reverse", False)),
                        "ws_reverse_url": str(onebot_cfg.get("ws_reverse_url") or ""),
                        "ws_reverse_targets": [
                            str(onebot_cfg.get(key) or "")
                            for key in (
                                "ws_reverse_url",
                                "ws_reverse_api_url",
                                "ws_reverse_event_url",
                            )
                            if str(onebot_cfg.get(key) or "").strip()
                        ],
                        "local_server": {
                            "enabled": bool(
                                onebot_cfg.get("enable_http") or onebot_cfg.get("enable_ws")
                            ),
                            "host": str(onebot_cfg.get("host") or ""),
                            "port": int(onebot_cfg.get("port") or 0),
                        },
                        "db_path": str(onebot_cfg.get("db_path") or ""),
                    },
                },
            }
        )

    async def _handle_credentials(self, _request: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "credentials": credentials_summary()})

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------

    def _log_lines(self) -> int:
        try:
            return int(self._config.get("log_lines") or DEFAULT_LOG_LINES)
        except (TypeError, ValueError):
            return DEFAULT_LOG_LINES

    async def _handle_logs_list(self, _request: web.Request) -> web.StreamResponse:
        return web.json_response(
            {"ok": True, "files": self._tailer.list_files(), "default": self._tailer.default_file}
        )

    async def _handle_logs_tail(self, request: web.Request) -> web.StreamResponse:
        name = request.query.get("file")
        try:
            lines = int(request.query.get("lines") or self._log_lines())
        except (TypeError, ValueError):
            lines = self._log_lines()
        try:
            payload = self._tailer.tail(name, lines)
        except FileNotFoundError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        return web.json_response({"ok": True, **payload})

    async def _handle_logs_stream(self, request: web.Request) -> web.StreamResponse:
        name = request.query.get("file")
        try:
            first_lines = int(request.query.get("lines") or self._log_lines())
        except (TypeError, ValueError):
            first_lines = self._log_lines()
        try:
            self._tailer.resolve(name)
        except FileNotFoundError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await response.prepare(request)
        try:
            async for chunk in self._tailer.stream(name, first_lines=first_lines):
                await response.write(chunk.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            with contextlib.suppress(Exception):
                await response.write_eof()
        return response

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------

    async def _handle_config_get(self, _request: web.Request) -> web.StreamResponse:
        return web.json_response(
            {
                "ok": True,
                "path": config_editor.CONFIG_PATH,
                "groups": config_editor.schema_payload(),
            }
        )

    async def _handle_config_post(self, request: web.Request) -> web.StreamResponse:
        payload = await self._read_json(request)
        if payload is None:
            return web.json_response({"ok": False, "error": "请求体必须是 JSON"}, status=400)
        try:
            result = await asyncio.to_thread(config_editor.apply_updates, payload.get("updates"))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            logger.exception("保存配置失败")
            return web.json_response({"ok": False, "error": f"保存失败：{exc}"}, status=500)
        return web.json_response({"ok": True, **result, "message": "已写入 config.py"})

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------

    async def _handle_api_login(self, request: web.Request) -> web.StreamResponse:
        payload = await self._read_json(request)
        if payload is None:
            return web.json_response({"ok": False, "error": "请求体必须是 JSON"}, status=400)
        try:
            result = await self._login.login_with_password(
                payload.get("phone", ""),
                payload.get("password", ""),
                timeout=float(payload.get("timeout") or 60.0),
            )
        except (ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            logger.error("Oopz 账号密码登录失败: %s", exc)
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **result})

    async def _handle_browser_login_status(self, _request: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "task": self._login.browser_login_status()})

    async def _handle_browser_login_start(self, request: web.Request) -> web.StreamResponse:
        payload = await self._read_json(request) or {}
        try:
            task = self._login.start_browser_login(
                phone=str(payload.get("phone") or ""),
                password=str(payload.get("password") or ""),
                headless=bool(payload.get("headless", False)),
            )
        except (ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "task": task})

    async def _handle_browser_login_cancel(self, _request: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, **await self._login.cancel_browser_login()})

    # ------------------------------------------------------------------
    # 桥接操作
    # ------------------------------------------------------------------

    async def _handle_bridge_restart(self, _request: web.Request) -> web.StreamResponse:
        await self._controller.restart("WebUI 手动重启")
        return web.json_response({"ok": True, "message": "已请求重启桥接"})

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    async def _read_json(request: web.Request) -> dict[str, Any] | None:
        try:
            payload = await request.json()
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None


__all__ = ["WebUIConsole"]
