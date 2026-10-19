from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from voice_agent.api import VoiceApiServer
from voice_agent.context_bridge import ContextBridge
from voice_agent.settings import VoiceApiSettings
from webui.voice_routes import build_voice_routes


def test_bridge_rpc_is_authenticated_correlated_and_rejects_second_instance():
    async def run():
        bridge = ContextBridge(timeout=1)
        runtime = SimpleNamespace(agent=SimpleNamespace(context_bridge=bridge, settings=SimpleNamespace(persona="local")))
        api = VoiceApiServer(runtime, VoiceApiSettings(token="test-secret"))
        app = web.Application()
        app.add_routes(build_voice_routes(runtime, wrap=api._wrap))
        async with TestClient(TestServer(app)) as client:
            first = "a" * 32
            second = "b" * 32
            assert (await client.get("/voice/astrbot/events")).status == 401
            assert (await client.get("/voice/astrbot/bindings")).status == 401
            headers = {"Authorization": "Bearer test-secret"}
            # Establish the same lease the real plugin owns before a room join.
            await bridge.poll(wait=0, client_id=first)
            prepare = asyncio.create_task(bridge.prepare("a", "c"))
            await asyncio.sleep(0)
            response = await client.get("/voice/astrbot/events", params={"client_id": first}, headers=headers)
            event = (await response.json())["events"][0]
            assert event["operation"] == "prepare"
            result = await client.post("/voice/astrbot/result", headers=headers, json={
                "request_id": event["request_id"], "client_id": first,
                "result": {"ok": True, "persona": "shared", "group_id": "123"}})
            assert (await result.json())["accepted"] is True
            await prepare
            assert bridge.persona == "shared"
            binding_request = asyncio.create_task(client.get("/voice/astrbot/bindings", headers=headers))
            await asyncio.sleep(0.01)
            response = await client.get("/voice/astrbot/events", params={"client_id": first}, headers=headers)
            binding_event = (await response.json())["events"][0]
            assert binding_event["operation"] == "bindings"
            assert binding_event["payload"] == {"action": "list"}
            bridge.resolve(binding_event["request_id"], {"ok": True, "bindings": []})
            assert (await (await binding_request).json())["bindings"] == []
            persona = await (await client.get("/persona", headers=headers)).json()
            assert persona["effective_persona"] == "shared"
            assert (await client.put("/persona", headers=headers, json={"persona": "ignored"})).status == 409
            assert (await client.get("/voice/astrbot/events", params={"client_id": second}, headers=headers)).status == 409
            assert (await client.post("/voice/astrbot/result", headers=headers, json={
                "request_id": event["request_id"], "client_id": second, "result": {"ok": True}})).status == 409
            assert (await client.post("/voice/astrbot/result", headers=headers, json={
                "request_id": event["request_id"], "client_id": first, "result": {"ok": True}})).status == 200
            bridge._last_poll = 0
            assert (await client.get("/voice/astrbot/bindings", headers=headers)).status == 503
            assert bridge.active and bridge.persona == "shared"
            assert (await client.put("/persona", headers=headers, json={"persona": "ignored"})).status == 409
    asyncio.run(run())
