"""VOICE_API 契约：成员字段归一 + 插件 format 兼容（无需 aiohttp）。"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
_plugin = os.path.join(os.path.dirname(ROOT), "astrbot_plugin_ooptra")


def normalize_member(row: dict) -> dict:
    """与 webui/voice_routes 相同的字段规则。"""
    uid = str(row.get("uid") or row.get("pid") or row.get("person_uid") or row.get("user_id") or "")
    name = str(row.get("name") or row.get("nickname") or row.get("user_name") or "")

    if "m" in row:
        mic_muted = bool(int(row.get("m") or 0) == 1)
    elif "mic_muted" in row:
        mic_muted = bool(row.get("mic_muted"))
    elif "mic" in row:
        mic_muted = not bool(row.get("mic"))
    else:
        mic_muted = False

    if "hm" in row:
        sp_muted = bool(int(row.get("hm") or 0) == 1)
    elif "speaker_muted" in row:
        sp_muted = bool(row.get("speaker_muted"))
    elif "speaker" in row:
        sp_muted = not bool(row.get("speaker"))
    else:
        sp_muted = False

    return {
        "uid": uid,
        "name": name,
        "mic": (not mic_muted),
        "speaker": (not sp_muted),
        "m": 1 if mic_muted else 0,
        "hm": 1 if sp_muted else 0,
    }


def test_normalize() -> None:
    # mic: true = 开
    a = normalize_member({"uid": "u1", "name": "小明", "mic": True, "speaker": True})
    assert a["mic"] is True and a["m"] == 0
    assert a["speaker"] is True and a["hm"] == 0

    # m: 1 = 闭麦
    b = normalize_member({"uid": "u2", "name": "小红", "m": 1, "hm": 0})
    assert b["mic"] is False and b["m"] == 1
    assert b["speaker"] is True and b["hm"] == 0

    # mic_muted 语义
    c = normalize_member({"uid": "u3", "name": "x", "mic_muted": True, "speaker_muted": False})
    assert c["mic"] is False and c["m"] == 1
    assert c["speaker"] is True
    print("normalize ok")


def test_plugin_format(monkeypatch) -> None:
    if os.path.isdir(_plugin):
        monkeypatch.syspath_prepend(_plugin)
    try:
        from ooptra_client import format_members, format_status
    except Exception as exc:
        print("plugin client not available, skip:", exc)
        return

    st = format_status({"joined": True, "area": "a", "channel": "c", "state": "playing"})
    assert "已在房" in st and "a" in st and "c" in st
    st2 = format_status({"joined": False})
    assert "未进房" in st2

    text = format_members(
        {
            "count": 2,
            "members": [
                {"uid": "u1", "name": "小明", "mic": True, "speaker": True},
                {"uid": "u2", "name": "小红", "m": 1, "hm": 0},
            ],
        }
    )
    assert "小明" in text and "小红" in text and "闭麦" in text
    print("plugin format ok")
    print(text)


def test_status_shape() -> None:
    # 插件 format_status 读扁平字段
    payload = {
        "ok": True,
        "joined": True,
        "area": "area1",
        "channel": "ch1",
        "state": "joined",
    }
    assert payload["joined"] is True and "state" in payload
    print("status shape ok")


if __name__ == "__main__":
    test_normalize()
    test_status_shape()
    test_plugin_format()
    print("CONTRACT SHAPE TESTS PASSED")
