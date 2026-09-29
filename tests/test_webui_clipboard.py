"""控制台的「复制」按钮在非安全上下文下也必须能用。

背景：``navigator.clipboard`` 只在**安全上下文**（https 或 localhost）存在。用
局域网 IP（``http://192.168.x.x:3090``）打开控制台时它是 ``undefined``，而旧实现
直接调 ``navigator.clipboard.writeText(...).then(...)`` —— 属性访问就已经抛
TypeError，``.then`` 根本不会执行，所以「复制域 ID / 频道 ID / 绑定指令」点了
既没复制成功、也不弹失败提示，看起来就是完全没反应。

这个文件锁三件事：必须判断可用性、必须有 execCommand 退路、退路也不灵时要让
用户能手动复制（prompt 里默认值是选中态）。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "webui" / "assets" / "app.js"


def _js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _fn(source: str, name: str) -> str:
    """按大括号配对截出 ``function <name>(...)`` 的函数体。"""
    match = re.search(rf"function\s+{re.escape(name)}\s*\(", source)
    assert match, f"app.js 里找不到 function {name}"
    start = source.index("{", match.end())
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"{name} 的大括号没有闭合")


# ----------------------------------------------------------------------
# copyText
# ----------------------------------------------------------------------


def test_clipboard_api_is_guarded() -> None:
    body = _fn(_js(), "copyText")
    assert "navigator.clipboard &&" in body, "用之前必须先判断 navigator.clipboard 存在"
    assert "isSecureContext" in body, "还要判断是不是安全上下文"


def test_no_unguarded_clipboard_call() -> None:
    """不允许出现「直接 writeText 再 .then」这种会同步抛错的写法。"""
    body = _fn(_js(), "copyText")
    for match in re.finditer(r"navigator\.clipboard\.writeText", body):
        head = body[: match.start()]
        assert "navigator.clipboard &&" in head, "writeText 必须在守卫之后调用"


def test_falls_back_to_exec_command() -> None:
    source = _js()
    assert "legacyCopy" in _fn(source, "copyText"), "非安全上下文要退回 execCommand"
    legacy = _fn(source, "legacyCopy")
    assert "execCommand('copy')" in legacy or 'execCommand("copy")' in legacy


def test_legacy_copy_cannot_throw() -> None:
    legacy = _fn(_js(), "legacyCopy")
    assert "try {" in legacy and "catch" in legacy, "DOM 操作失败也不能把异常抛出去"


def test_manual_copy_is_offered_as_last_resort() -> None:
    body = _fn(_js(), "copyText")
    assert "window.prompt(" in body, "两条路都失败时要让用户能手动复制"


def test_failure_reports_a_reason() -> None:
    body = _fn(_js(), "copyText")
    assert "toast(" in body, "失败必须给出提示，不能静默"
    assert "复制失败" in body
