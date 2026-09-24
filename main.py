"""Ooptra 入口：Oopz <-> OneBot v11 反向 WebSocket 桥接 + 本地 Web 控制台。"""

import asyncio
import contextlib
import os
import signal
import sys

if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>&1")

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from bridge.app import BridgeController
from bridge.runtime import apply_runtime_overrides, validate_runtime_config
from bridge.state import BridgeState
from core.logger_config import setup_logger
from core.version import __version__
from webui.server import WebUIConsole

logger = setup_logger("Main")


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_stop(_sig: signal.Signals) -> None:
        stop_event.set()

    signals = [signal.SIGINT, signal.SIGTERM]
    # Windows 控制台没有 SIGTERM；Ctrl+Break（含 taskkill 的软关闭）走 SIGBREAK。
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        signals.append(sigbreak)

    for sig in signals:
        try:
            loop.add_signal_handler(sig, request_stop, sig)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_args: loop.call_soon_threadsafe(stop_event.set))


async def run() -> None:
    from config import WEBUI_CONFIG

    state = BridgeState()
    controller = BridgeController(state)
    console = WebUIConsole(state, controller, config=WEBUI_CONFIG)

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    logger.info("=" * 56)
    logger.info("Ooptra v%s · Oopz <-> OneBot v11 反向 WebSocket 桥接", __version__)
    logger.info("=" * 56)

    # 先起控制台：即使凭据失效或对端还没起来，也能在网页上查看状态并登录。
    await console.start()
    await controller.start()

    try:
        await stop_event.wait()
    finally:
        await controller.stop()
        await console.stop()
    logger.info("桥接已停止。")


def main() -> None:
    apply_runtime_overrides()
    validate_runtime_config()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
