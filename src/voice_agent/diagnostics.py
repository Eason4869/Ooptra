"""Actionable bounded checks, using disposable resources for network probes."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import importlib.util
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from voice_agent.backends import create_backend
from voice_agent.preview import EphemeralMemory
from voice_agent.settings import resolve_agent_proxy_url


async def diagnose(agent, *, network: bool = False) -> dict:
    checks = []
    def add(key, title, state, detail):
        checks.append({"id": key, "title": title, "state": state, "detail": detail})
    settings = agent.settings
    mimo = settings.backend in {"mimo", "mimo_cascade", "cascade", "cascade_mimo"}
    add("python", "Python 环境", "pass" if sys.version_info >= (3, 10) else "fail",
        ".".join(map(str, sys.version_info[:3])))
    available = importlib.util.find_spec("playwright") is not None
    add("playwright", "语音浏览器依赖", "pass" if available else "fail",
        "已安装" if available else "请安装 requirements-optional.txt，再安装 Chromium")
    if available:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as manager:
                installed = Path(manager.chromium.executable_path).is_file()
            add("chromium", "Chromium", "pass" if installed else "fail",
                "内核已安装" if installed else "运行 python -m playwright install chromium")
        except Exception:
            add("chromium", "Chromium", "fail", "浏览器驱动检查失败，请重新安装可选依赖与 Chromium")
    else:
        add("chromium", "Chromium", "skipped", "先安装 Playwright")
    connected = bool(agent._bot is not None and getattr(agent, "_connection_ready", True))
    add("oopz", "Oopz 连接", "pass" if connected else "fail",
        "已连接" if connected else "请先在账号页登录，并确认桥接连接状态")
    key = settings.mimo_api_key if mimo else settings.gemini_api_key
    from voice_agent.backends.gemini_live import live_url_has_key
    configured = bool(key or (not mimo and live_url_has_key(settings.gemini_base_url)))
    add("credentials", "模型凭据", "pass" if configured else "fail",
        "已配置；有效性由网络检查确认" if configured else "请在语音模型配置中填写密钥")
    model = settings.mimo_llm_model if mimo else settings.gemini_model
    add("model", "模型配置", "pass" if model else "fail", model or "请选择模型")
    valid_rate = 8000 <= settings.sample_rate_in <= 96000 and 8000 <= settings.sample_rate_out <= 96000
    add("sample_rate", "音频采样率", "pass" if valid_rate else "fail",
        f"输入 {settings.sample_rate_in} Hz / 输出 {settings.sample_rate_out} Hz")
    try:
        proxy = resolve_agent_proxy_url(settings.proxy)
        if proxy and urlsplit(proxy).scheme not in {"http", "https"}:
            raise ValueError("unsupported proxy")
        add("proxy", "模型网络出口", "pass", "已配置代理" if proxy else "直连/系统出口")
    except Exception:
        add("proxy", "模型网络出口", "fail", "代理地址无效，请检查协议、地址与端口")
    if not network or not configured:
        add("network", "模型连接", "skipped", "点击网络检查验证连接" if configured else "先配置模型密钥")
    else:
        started = time.monotonic()
        backend = None
        try:
            backend = create_backend(dataclasses.replace(settings), EphemeralMemory())
            async def probe():
                if mimo:
                    await backend.detect_leave_intent("你好，请保持在语音房，不要退出")
                else:
                    await backend.start_session()
            await asyncio.wait_for(probe(), 20)
            add("network", "模型连接", "pass", "MiMo 对话模型请求成功；ASR 和 TTS 可用性需实际语音或试听确认" if mimo else "Live 会话建立成功；未加入语音房")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            add("network", "模型连接", "fail",
                f"{type(exc).__name__}：连接失败，请核对密钥、模型权限和网络出口")
        finally:
            if backend is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(backend.aclose(), 3)
        checks[-1]["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return {"checks": checks, "passed": all(item["state"] != "fail" for item in checks),
            "network_checked": network and configured}
