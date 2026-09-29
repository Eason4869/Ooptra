"""检查更新接口：代理配置解析不能把 500 留给用户。

回归锁死一个真实故障：``str(getattr(cfg, "VOICE_AGENT_CONFIG", {})).get("proxy")``
先把字典转成了字符串，再对字符串调 ``.get()`` —— 无条件抛 AttributeError，
「检查更新」100% 返回 HTTP 500（且和网络、GitHub 可达性毫无关系，极易误判）。
"""

from __future__ import annotations

import asyncio
import types

import pytest

from webui import server as webui_server
from webui import update_check


class _DummyConsole:
    """handler 只用到 runtime_config 与两个函数，其余 self 属性不参与。"""


def _run_update_check(monkeypatch: pytest.MonkeyPatch, agent_config: object) -> dict:
    """用假的 check_github_update 调一次 handler，返回它实际拿到的 proxy。"""
    captured: dict[str, object] = {}

    async def fake_check(*, proxy: object = None, **_kwargs: object) -> dict:
        captured["proxy"] = proxy
        return {"ok": True, "current_version": "2.0.0"}

    monkeypatch.setattr(update_check, "check_github_update", fake_check)
    monkeypatch.setattr(
        webui_server, "runtime_config", types.SimpleNamespace(VOICE_AGENT_CONFIG=agent_config)
    )

    response = asyncio.run(webui_server.WebUIConsole._handle_update_check(_DummyConsole(), None))
    assert response.status == 200
    return captured


def test_dict_config_resolves_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常的 dict 配置：proxy 必须被真正读到，而不是被静默忽略。"""
    captured = _run_update_check(monkeypatch, {"proxy": "clash"})
    assert captured["proxy"] == "http://127.0.0.1:7890"


def test_dict_config_without_proxy_is_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _run_update_check(monkeypatch, {"proxy": ""})
    assert captured["proxy"] is None


def test_missing_group_is_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """config.py 里没有 VOICE_AGENT_CONFIG 时也要能跑，不能 KeyError。"""
    monkeypatch.setattr(webui_server, "runtime_config", types.SimpleNamespace())
    captured: dict[str, object] = {}

    async def fake_check(*, proxy: object = None, **_kwargs: object) -> dict:
        captured["proxy"] = proxy
        return {"ok": True}

    monkeypatch.setattr(update_check, "check_github_update", fake_check)
    response = asyncio.run(webui_server.WebUIConsole._handle_update_check(_DummyConsole(), None))
    assert response.status == 200
    assert captured["proxy"] is None


def test_non_dict_config_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置被写成字符串（历史事故的形态）时，宁可直连也不要 500。"""
    captured = _run_update_check(monkeypatch, "clash")
    assert captured["proxy"] is None
