"""Updater hooks preserve the formal branch's existing console contract."""

import asyncio
import importlib.util
import io
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import aiohttp

from webui import server


def test_console_mounts_maintenance_without_replacing_formal_status(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PROJECT_ROOT", str(tmp_path))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    controller = SimpleNamespace(snapshot=lambda: {
        "runtime": {"supervisor_alive": True},
        "oopz": {"connected": False}, "onebot": {"connected": False},
    })

    async def run():
        console = server.WebUIConsole(None, controller, config={"port": port, "token": "secret"})
        await console.start()
        try:
            async with aiohttp.ClientSession() as client:
                endpoint = f"http://127.0.0.1:{port}"
                denied = await client.get(endpoint + "/api/maintenance")
                assert denied.status == 401
                auth = {"Authorization": "Bearer secret"}
                response = await client.get(endpoint + "/api/maintenance", headers=auth)
                assert response.status == 200
                maintenance = await response.json()
                assert maintenance["preflight"]["supported"] is False
                assert maintenance["update"]["version"] == "3.1.0"
                status = await (await client.get(endpoint + "/api/status", headers=auth)).json()
                assert status["process"]["version"] == "3.1.0"
                assert status["bridge"]["runtime"]["supervisor_alive"] is True
                assert "voice" in status["config"]
        finally:
            await console.stop()

    asyncio.run(run())


def test_local_bootstrap_readiness_is_independent_of_remote_connections():
    controller = SimpleNamespace(snapshot=lambda: {
        "runtime": {"supervisor_alive": True},
        "oopz": {"connected": False}, "onebot": {"connected": False},
    })
    console = server.WebUIConsole(None, controller)
    payload = json.loads(asyncio.run(console._handle_status(None)).text)
    assert payload["process"].get("bootstrap_ready") is False
    console.set_bootstrap_ready(True)
    payload = json.loads(asyncio.run(console._handle_status(None)).text)
    assert payload["health"]["process_ok"] is True
    assert payload["health"]["state"] == "degraded"


def test_launcher_control_requests_graceful_shutdown(monkeypatch):
    spec = importlib.util.spec_from_file_location("formal_entry", Path(__file__).resolve().parents[1] / "main.py")
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)

    install = getattr(main, "_install_managed_control", None)
    assert callable(install), "launcher must be able to stop the bot before switching its files"
    monkeypatch.setenv("OOPTRA_MANAGED", "1")
    monkeypatch.setattr(main.sys, "stdin", io.StringIO("ignored\nOOPTRA_STOP\n"))

    async def run():
        stop = asyncio.Event()
        install(stop)
        await asyncio.wait_for(stop.wait(), timeout=2)
        assert stop.is_set()

    asyncio.run(run())
