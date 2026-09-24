"""本地 Web 控制台：查看状态/日志、编辑配置、登录 Oopz。"""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["WebUIConsole"]

if TYPE_CHECKING:
    from webui.server import WebUIConsole


def __getattr__(name: str):
    """延迟导入，避免仅使用 webui.config_editor 时也要求 config.py 存在。"""
    if name == "WebUIConsole":
        from webui.server import WebUIConsole

        return WebUIConsole
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
