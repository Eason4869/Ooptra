"""重启通知必须被消费，启动期间到达的通知也不能丢。"""

from __future__ import annotations

import asyncio

from bridge.app import BridgeController
from bridge.state import BridgeState


def test_restart_returns_supervisor_to_blocking_wait(monkeypatch):
    async def run():
        controller = BridgeController(BridgeState())
        waits = 0
        starts = 0
        original_wait = controller._wait_run

        async def start_bot():
            nonlocal starts
            starts += 1
            controller._bot = object()
            controller._run_task = asyncio.create_task(asyncio.Event().wait())

        async def teardown():
            task, controller._run_task = controller._run_task, None
            controller._bot = None
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        async def wait_run():
            nonlocal waits
            waits += 1
            await original_wait()

        monkeypatch.setattr(controller, "_start_bot", start_bot)
        monkeypatch.setattr(controller, "_teardown", teardown)
        monkeypatch.setattr(controller, "_wait_run", wait_run)
        await controller.start()
        try:
            for _ in range(20):
                await asyncio.sleep(0)
            assert waits == 1
            await controller.restart("first")
            for _ in range(60):
                await asyncio.sleep(0)
            assert starts == 2
            assert waits == 2, "已完成重启却还在重复进入等待循环"
            await controller.restart("second")
            for _ in range(60):
                await asyncio.sleep(0)
            assert starts == 3
            assert waits == 3
        finally:
            await controller.stop()

    asyncio.run(run())


def test_retry_wait_keeps_notification_received_during_startup():
    async def run():
        controller = BridgeController(BridgeState())
        controller._wake.set()
        await asyncio.wait_for(controller._wait_wake(10), timeout=0.1)

    asyncio.run(run())


def test_restart_during_startup_is_processed(monkeypatch):
    async def run():
        controller = BridgeController(BridgeState())
        entered = asyncio.Event()
        release = asyncio.Event()
        starts = 0

        async def start_bot():
            nonlocal starts
            starts += 1
            if starts == 1:
                entered.set()
                await release.wait()
                raise RuntimeError("initial connection failed")
            controller._bot = object()
            controller._run_task = asyncio.create_task(asyncio.Event().wait())

        async def teardown():
            task, controller._run_task = controller._run_task, None
            controller._bot = None
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        monkeypatch.setattr(controller, "_start_bot", start_bot)
        monkeypatch.setattr(controller, "_teardown", teardown)
        await controller.start()
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await controller.restart("new credentials")
            release.set()
            for _ in range(60):
                await asyncio.sleep(0)
            assert starts == 2, "启动失败覆盖了等待中的重启通知"
            assert controller.state.restarts == 1
        finally:
            await controller.stop()

    asyncio.run(run())
