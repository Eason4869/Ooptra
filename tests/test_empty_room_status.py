import asyncio

from test_auto_visit_controller import scenario


def test_countdown_and_unknown_membership_are_visible(tmp_path):
    async def run():
        ctrl, agent, clock, _, _ = scenario(tmp_path)
        agent.joined, agent.area, agent.channel, agent.source = True, "a", "one", "manual"
        agent.rooms["a"]["one"] = [{"uid": "bot"}]
        assert not await ctrl._room_empty_confirmed()
        assert ctrl.status()["empty_room"]["remaining_seconds"] == 30
        clock.advance(29)
        assert ctrl.status()["empty_room"]["remaining_seconds"] == 1
        agent.fail_queries.add("a")
        assert not await ctrl._room_empty_confirmed()
        state = ctrl.status()["empty_room"]
        assert state["state"] == "unknown"
        assert state["remaining_seconds"] is None
        assert state["error"]
        agent.fail_queries.clear()
        await ctrl._room_empty_confirmed()
        clock.advance(30)
        await ctrl._check_empty_room()
        assert ctrl.status()["empty_room"]["last_exit_reason"] == "alone_30_seconds"
        await ctrl.stop()
    asyncio.run(run())
