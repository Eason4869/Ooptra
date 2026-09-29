"""成员页必须只查 bot 所在的那个语音房，并把「没收到」和「未广播」说清楚。

背景：``/api/voice/members`` 不传 ``channel`` 时是**整个域汇总**，而静音状态只有
同一个 Agora 房间里的人会广播。前端以前只传 ``area``，于是别房的成员全被列出来，
他们的状态永远只能是「未知」——用户看到的就是「成员列表的麦克风/扬声器没修好」。

这个文件锁三件事：
  1. 先读 /api/voice/status 拿到 bot 此刻在哪个房，再带上 ``channel`` 去查
  2. bot 不在房时不硬编一个频道，退回按域查询并在状态行说明原因
  3. 没有实时状态的行显示「未广播」（是对方没发），而不是含糊的「未知」；
     状态行报「本房 M/N 人」而不是累计广播条数
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "src" / "webui" / "assets" / "app.js"


def _js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _fn(source: str, name: str) -> str:
    """按大括号配对截出 ``[async] function <name>(...) {...}``。"""
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


def _body() -> str:
    return _fn(_js(), "refreshMembers")


# ----------------------------------------------------------------------
# 查询范围
# ----------------------------------------------------------------------


def test_members_asks_for_the_bot_current_channel() -> None:
    body = _body()
    assert "api('/api/voice/status')" in body, "要先问 bot 在哪个房"
    assert re.search(r"qs\s*\+=\s*'&channel='\s*\+\s*encodeURIComponent\(channel\)", body), (
        "必须把 channel 拼进查询串，否则接口会汇总整个域"
    )


def test_channel_comes_from_status_not_from_a_guess() -> None:
    body = _body()
    assert re.search(r"st\.joined\s*&&\s*st\.channel", body), (
        "频道只能取 status 里的值，且必须确认在房；不能拿 area 或默认值顶替"
    )


def test_area_falls_back_to_status_when_input_is_empty() -> None:
    body = _body()
    assert re.search(r"if\s*\(!area\)\s*area\s*=\s*st\.area", body), (
        "输入框为空时应回落到 status 的 area"
    )


def test_not_joined_falls_back_to_area_only_query() -> None:
    """未在房时不该编一个 channel —— 按域查询可以，但状态行要说明。"""
    body = _body()
    assert re.search(r"if\s*\(!channel\)", body), "要处理 bot 不在房的情况"
    assert "未在语音房" in body


# ----------------------------------------------------------------------
# 展示
# ----------------------------------------------------------------------


def test_unreported_state_is_labelled_honestly() -> None:
    body = _body()
    assert "未广播" in body, "没实时状态的行要写「未广播」，不能写「未知」"
    # 未知分支里不能出现 onText —— 那会把「没收到」渲染成「开麦」
    start = body.index("if (flag === null")
    branch = body[start : body.index("未广播", start)]
    assert "onText" not in branch, "未知分支不能落到「开麦/正常」文案"


def test_status_line_reports_resolved_members_not_broadcast_count() -> None:
    body = _body()
    assert "data.live_members" in body, "状态行要读 live_members（已解析人数）"
    assert "got + '/' + total" in body, "状态行要显示 M/N"
    # 累计广播条数容易让人以为「收到 7 条」就是 7 个人，不再展示
    assert "live_state_received" not in body, (
        "live_state_received 是累计广播条数，不该继续当人数展示"
    )


def test_no_member_request_without_area_param() -> None:
    """area 必定出现在查询串里（接口缺 area 会直接 400）。"""
    body = _body()
    assert re.search(r"let\s+qs\s*=\s*'\?area='", body), "查询串必须以 ?area= 开头"
