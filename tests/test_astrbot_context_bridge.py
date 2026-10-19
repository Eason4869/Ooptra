from __future__ import annotations

import asyncio
import json

from voice_agent.context_bridge import ContextBridge


def test_prepare_uses_correlated_reply_and_drops_stale_results():
    async def run():
        bridge = ContextBridge(timeout=0.1)
        await bridge.poll(wait=0)
        task = asyncio.create_task(bridge.prepare("area", "room"))
        await asyncio.sleep(0)
        request = (await bridge.poll(wait=0))[0]
        assert request["operation"] == "prepare"
        assert request["room"] == {"area": "area", "channel": "room"}
        assert not bridge.resolve("wrong", {"ok": True})
        bridge.resolve(request["request_id"], {
            "ok": True, "persona": "AstrBot persona", "group_id": "123", "umo": "qq:GroupMessage:123",
        })
        await task
        assert bridge.persona == "AstrBot persona"
        old_session = bridge.session_id
        bridge.clear()
        assert bridge.session_id != old_session
        assert not bridge.active
        assert not bridge.resolve(request["request_id"], {"ok": True})
    asyncio.run(run())


def test_outbox_survives_restart_and_acknowledges_only_matching_request(tmp_path):
    async def run():
        path = tmp_path / "outbox.json"
        bridge = ContextBridge(outbox_path=path)
        bridge.context = {"ok": True, "group_id": "123", "umo": "qq:GroupMessage:123"}
        bridge.room = {"area": "a", "channel": "c"}
        bridge.record_turn("hello", "hi", speaker="oopz-user", interrupted=False)
        restored = ContextBridge(outbox_path=path)
        event = (await restored.poll(wait=0))[0]
        assert event["operation"] == "commit"
        assert event["payload"]["user_text"] == "hello"
        assert event["scope"]["group_id"] == "123"
        assert restored.resolve(event["request_id"], {"ok": True})
        assert json.loads(path.read_text(encoding="utf-8")) == []
        assert not restored.resolve(event["request_id"], {"ok": True})
    asyncio.run(run())


def test_offline_scope_never_uses_last_rooms_persona():
    async def run():
        bridge = ContextBridge(timeout=0.01)
        bridge.context = {"ok": True, "persona": "old"}
        await bridge.prepare("other", "room")
        assert bridge.persona == ""
        assert not bridge.active
        assert bridge.status()["state"] == "offline"
    asyncio.run(run())


def test_interrupted_reply_is_not_written_as_complete_assistant_turn():
    bridge = ContextBridge()
    bridge.context = {"ok": True, "umo": "qq:GroupMessage:123"}
    bridge.record_turn("question", "unfinished", speaker="", interrupted=True)
    event = next(iter(bridge.outbox.values()))
    assert event["payload"]["reply_text"] == ""
    assert event["payload"]["interrupted"] is True


def test_binding_management_survives_voice_room_switch():
    async def run():
        bridge = ContextBridge(timeout=1)
        await bridge.poll(wait=0)
        task = asyncio.create_task(bridge.request("bindings", {"action": "save"}))
        await asyncio.sleep(0)
        event = (await bridge.poll(wait=0))[0]
        bridge._leased[event["request_id"]] -= 9
        assert await bridge.poll(wait=0) == [], "slow configuration writes must not be delivered twice"
        bridge.clear()
        assert bridge.resolve(event["request_id"], {"ok": True, "bindings": []})
        assert (await task)["ok"] is True
    asyncio.run(run())
