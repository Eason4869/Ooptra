import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from webui.maintenance import MaintenanceService, mount_maintenance_routes
from webui.server import WebUIConsole


def test_backup_routes_require_auth_and_reject_cross_origin_posts(tmp_path):
    async def run():
        console = WebUIConsole(None, None)
        console._token = "test-token"
        app = web.Application(middlewares=[console._auth_middleware])
        service = MaintenanceService(tmp_path)
        mount_maintenance_routes(app, service)
        async with TestClient(TestServer(app)) as client:
            assert (await client.post("/api/maintenance/backups", json={})).status == 401
            denied = await client.post("/api/maintenance/backups", json={}, headers={"Authorization": "Bearer test-token", "Origin": "https://untrusted.example"})
            assert denied.status == 400
            response = await client.post("/api/maintenance/backups", json={}, headers={"Authorization": "Bearer test-token"})
            assert response.status == 200
            backup = await response.json()
            assert (await client.get("/api/maintenance/backups/" + backup["id"])).status == 401
            download = await client.get("/api/maintenance/backups/" + backup["id"], headers={"Authorization": "Bearer test-token"})
            assert download.status == 200
            assert (await download.read()).startswith(b"PK")
    asyncio.run(run())
