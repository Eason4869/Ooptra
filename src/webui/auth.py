"""Browser sessions use opaque cookies; plugin credentials remain independent of logout."""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

SESSION_COOKIE = "ooptra_session"
SESSION_SECONDS = 12 * 3600
AUTH_PATHS = {"/api/auth/status", "/api/auth/login", "/api/auth/logout", "/api/auth/setup"}


class ConsoleAuth:
    def __init__(self, token: Callable[[], str], save_password: Callable[..., Any]) -> None:
        self._token = token
        self._save_password = save_password
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, tuple[int, float]] = {}
        self._setup_lock = asyncio.Lock()

    def mount(self, app: web.Application) -> None:
        app.add_routes([
            web.get("/api/auth/status", self.status),
            web.post("/api/auth/login", self.login),
            web.post("/api/auth/logout", self.logout),
            web.post("/api/auth/setup", self.setup),
        ])

    def invalidate(self) -> None:
        self._sessions.clear()

    def authenticated(self, request: web.Request) -> bool:
        now = time.time()
        self._sessions = {sid: deadline for sid, deadline in self._sessions.items() if deadline > now}
        return bool(self._token() and request.cookies.get(SESSION_COOKIE) in self._sessions)

    def plugin_authenticated(self, request: web.Request) -> bool:
        token = self._token()
        provided = (str(request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
                    or request.headers.get("X-Ooptra-Token") or request.query.get("token") or "")
        return bool(token and hmac.compare_digest(str(provided).encode(), token.encode()))

    @staticmethod
    def same_origin(request: web.Request) -> bool:
        origin = request.headers.get("Origin")
        return (not origin or origin == f"{request.scheme}://{request.host}") and request.headers.get("Sec-Fetch-Site") != "cross-site"

    @staticmethod
    def setup_allowed(request: web.Request) -> bool:
        try:
            host = urlsplit(f"http://{request.host}").hostname or ""
            local_host = host in {"localhost", "localhost.localdomain"} or ipaddress.ip_address(host).is_loopback
            return local_host and ipaddress.ip_address(request.remote or "").is_loopback
        except ValueError:
            return False

    async def status(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "configured": bool(self._token()),
                                  "authenticated": self.authenticated(request),
                                  "setup_allowed": not self._token() and self.setup_allowed(request)},
                                 headers={"Cache-Control": "no-store"})

    async def _password(self, request: web.Request) -> str:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="请求体必须是 JSON") from None
        password = body.get("password") if isinstance(body, dict) else None
        if not isinstance(password, str) or not password.strip() or len(password) > 1024:
            raise web.HTTPBadRequest(text="请填写有效的控制台密码（最多 1024 字符）")
        return password.strip()

    def _logged_in(self, request: web.Request) -> web.Response:
        self.authenticated(request)  # Prune expired sessions before issuing another.
        if len(self._sessions) >= 128:
            self._sessions.pop(next(iter(self._sessions)))
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = time.time() + SESSION_SECONDS
        response = web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})
        response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Lax",
                            secure=request.secure, max_age=SESSION_SECONDS, path="/")
        response.del_cookie("oopz_webui_token", path="/")
        return response

    async def login(self, request: web.Request) -> web.Response:
        password = await self._password(request)
        now = time.time()
        self._failures = {key: value for key, value in self._failures.items() if value[1] > now}
        key = request.remote or "unknown"
        failures, deadline = self._failures.get(key, (0, now + 60))
        if failures >= 10:
            return web.json_response({"ok": False, "error": "尝试过多，请一分钟后重试"}, status=429)
        if not self._token() or not hmac.compare_digest(password.encode(), self._token().encode()):
            if len(self._failures) >= 1024:
                self._failures.pop(next(iter(self._failures)))
            self._failures[key] = (failures + 1, deadline)
            return web.json_response({"ok": False, "error": "控制台密码不正确"}, status=401)
        self._failures.pop(key, None)
        return self._logged_in(request)

    async def logout(self, request: web.Request) -> web.Response:
        self._sessions.pop(request.cookies.get(SESSION_COOKIE, ""), None)
        response = web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})
        response.del_cookie(SESSION_COOKIE, path="/")
        response.del_cookie("oopz_webui_token", path="/")
        return response

    async def setup(self, request: web.Request) -> web.Response:
        if not self.setup_allowed(request):
            return web.json_response({"ok": False, "error": "请在部署机器本机设置首次密码"}, status=403)
        password = await self._password(request)
        async with self._setup_lock:
            if self._token():
                return web.json_response({"ok": False, "error": "密码已设置，请登录后在系统配置中修改"}, status=409)
            try:
                await self._save_password(password)
            except Exception:
                return web.json_response({"ok": False, "error": "密码保存失败，请检查配置文件权限后重试"}, status=500)
        return self._logged_in(request)
