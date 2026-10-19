"""Page URLs deliver the shell while audio writes retain API authentication."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from webui.server import PAGE_PATHS
from webui.voice_routes import mount_voice_routes


def test_deep_pages_assets_unknown_routes_and_protected_output():
    from test_webui_auth import console_app

    async def run():
        console, app = console_app()
        app.add_routes([web.get(path, console._handle_index) for path in PAGE_PATHS])
        app.router.add_get("/assets/{name}", console._handle_asset)
        setter = AsyncMock(return_value={"ok": True, "volume": 35, "muted": False, "saved": True})
        mount_voice_routes(app, SimpleNamespace(agent=SimpleNamespace(set_output_controls=setter)))
        async with TestClient(TestServer(app)) as client:
            for path in PAGE_PATHS:
                response = await client.get(path)
                assert response.status == 200 and response.content_type == "text/html"
                assert '/assets/voice.js' in await response.text()
                assert "no-cache" in response.headers["Cache-Control"]
            assert (await client.get("/assets/voice.js")).status == 200
            assert (await client.get("/missing-page")).status == 404
            for path in ("/api/voice/output", "/voice/output"):
                count = setter.await_count
                assert (await client.post(path, json={"volume": 35})).status == 401
                assert setter.await_count == count
                response = await client.post(path, json={"volume": 35},
                                             headers={"Authorization": "Bearer shared-password"})
                assert response.status == 200 and (await response.json())["volume"] == 35
            assert setter.await_count == 2
    asyncio.run(run())
