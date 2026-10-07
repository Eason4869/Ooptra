"""Server-side Git update transport; mirrors never choose the installed commit.

The official lookup runs outside the checkout with global/system Git configuration
disabled, so url.*.insteadOf cannot silently replace the trust source. Proxy URLs
are passed in child environment configuration, never command arguments or errors.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

OFFICIAL_URL = "https://github.com/Eason4869/Ooptra.git"
_CHANNELS = {"main", "beta", "dev"}
_PROXY_SCHEMES = {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}
_PROXY_ENV = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}


def validate_network_field(field, value):
    """Validate before saving, without including a secret input in the error."""
    if field not in {"update_proxy", "update_mirror"}:
        raise ValueError("未知更新网络配置项")
    hint = "更新代理需填写完整代理 URL、direct 或留空" if field == "update_proxy" else "更新镜像需填写完整 HTTPS Git 仓库 URL 或留空"
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError(hint)
    if any(ord(char) < 32 or ord(char) == 127 for char in unquote(value)):
        raise ValueError(hint)
    value = value.strip()
    if not value:
        return ""
    if field == "update_proxy" and value.lower() == "direct":
        return "direct"
    try:
        parsed = urlsplit(value)
        if not parsed.hostname or (parsed.port is not None and not 1 <= parsed.port <= 65535):
            raise ValueError
        if any(char.isspace() for char in value) or any(char in value for char in "\\?#"):
            raise ValueError
        if field == "update_proxy":
            if parsed.scheme not in _PROXY_SCHEMES or parsed.path not in {"", "/"}:
                raise ValueError
        elif (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
              or not parsed.path.strip("/") or any(char in value for char in "{}")):
            raise ValueError
    except ValueError:
        raise ValueError(hint) from None
    return value


@dataclass(frozen=True)
class NetworkSettings:
    proxy: str = field(default="", repr=False)
    mirror: str = ""

    def __post_init__(self):
        object.__setattr__(self, "proxy", validate_network_field("update_proxy", self.proxy))
        object.__setattr__(self, "mirror", validate_network_field("update_mirror", self.mirror))


def load_network_settings():
    """Read the synchronized runtime dictionary for each new operation."""
    from config import WEBUI_CONFIG

    return NetworkSettings(WEBUI_CONFIG.get("update_proxy", ""), WEBUI_CONFIG.get("update_mirror", ""))


def _git_environment(proxy, url=OFFICIAL_URL, *, isolated=False):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("GIT_CONFIG_", "GIT_TRACE")) or key in {"GIT_CONFIG", "GIT_SSL_NO_VERIFY", "GIT_CURL_VERBOSE"}:
            env.pop(key, None)
        if proxy and key.lower() in _PROXY_ENV:
            env.pop(key, None)
    pairs = []
    if proxy:
        pairs.append(("http.proxy", "" if proxy == "direct" else proxy))
        pairs.append((f"http.{url}.proxy", "" if proxy == "direct" else proxy))
    redirects = "false" if isolated else "initial"
    pairs.extend([("http.sslVerify", "true"), (f"http.{url}.sslVerify", "true"),
                  ("http.followRedirects", redirects), (f"http.{url}.followRedirects", redirects)])
    env["GIT_CONFIG_COUNT"] = str(len(pairs))
    for index, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never", GIT_OPTIONAL_LOCKS="0")
    if isolated:
        env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
            env.pop(key, None)
    return env


def _timeout(deadline, attempts_left=1, maximum=15):
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise ValueError("更新网络操作总耗时已超时，请检查部署服务器网络后重试")
    return min(maximum, budget / attempts_left)


def _valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value) is not None


def _validate_channel(channel):
    if not isinstance(channel, str) or channel not in _CHANNELS:
        raise ValueError("仅支持 main、beta 或 dev 更新源")


def _api_sha(channel, timeout, proxy):
    """Official API fallback, with redirects disabled and TLS always verified."""
    url = f"https://api.github.com/repos/Eason4869/Ooptra/commits/heads/{channel}"
    with requests.Session() as session:
        session.trust_env = not proxy
        if proxy and proxy != "direct":
            session.proxies.update(http=proxy, https=proxy)
        with session.get(url, headers={"Accept": "application/vnd.github.sha", "User-Agent": "Ooptra-Updater"},
                         timeout=timeout, allow_redirects=False, stream=True, verify=True) as response:
            if response.status_code != 200:
                raise ValueError("官方 GitHub API 查询失败")
            body = bytearray()
            read_deadline = time.monotonic() + timeout
            for chunk in response.iter_content(chunk_size=128):
                if time.monotonic() >= read_deadline or len(body) + len(chunk) > 128:
                    raise ValueError("官方 GitHub API 响应超时或无效")
                body.extend(chunk)
            sha = body.decode("ascii").strip()
    if not _valid_sha(sha):
        raise ValueError("官方 GitHub API 返回的提交无效")
    return sha


def lookup_official_sha(root, channel, deadline, run_command, *, settings=None, progress=None):
    """Resolve the channel only from verified official HTTPS; never from mirrors."""
    _validate_channel(channel)
    settings = load_network_settings() if settings is None else settings
    git_proxies = [settings.proxy] if settings.proxy == "direct" else [settings.proxy, "direct"]
    api_proxies = [settings.proxy] if settings.proxy == "direct" else [settings.proxy, "direct"]
    # requests' optional SOCKS extra is not part of the deployment contract.
    api_proxies = [proxy for proxy in api_proxies if not proxy.startswith("socks")]
    attempts = [("git", proxy) for proxy in git_proxies] + [("api", proxy) for proxy in api_proxies]
    for index, (kind, proxy) in enumerate(attempts):
        timeout = _timeout(deadline, len(attempts) - index)
        label = "官方 GitHub API" if kind == "api" else "官方 GitHub"
        if progress:
            progress(f"查询{label}（{'直连' if proxy == 'direct' else '服务器网络出口'}），尝试 {index + 1}/{len(attempts)}")
        try:
            if kind == "api":
                sha = _api_sha(channel, timeout, proxy)
            else:
                with tempfile.TemporaryDirectory(prefix="ooptra-update-source-") as directory:
                    env = _git_environment(proxy, isolated=True)
                    env["GIT_CEILING_DIRECTORIES"] = str(Path(directory).parent)
                    output = run_command(Path(directory), ["git", "ls-remote", OFFICIAL_URL, f"refs/heads/{channel}"],
                                         timeout, env=env)
                rows = [row.split() for row in output.splitlines()]
                sha = next((row[0] for row in rows if len(row) == 2 and row[1] == f"refs/heads/{channel}"), "")
            if _valid_sha(sha):
                _timeout(deadline)
                return sha
        except (OSError, ValueError, subprocess.TimeoutExpired, requests.RequestException, UnicodeError):
            pass
    raise ValueError("无法核对官方更新版本；已尝试服务器网络出口、直连及官方 API。请配置部署服务器更新代理后重试；镜像不能替代官方版本校验")


def fetch_verified(root, channel, trusted_sha, deadline, run_command, *, settings=None, progress=None):
    """Try official transports, then the configured mirror, pinning every fetch."""
    _validate_channel(channel)
    if not _valid_sha(trusted_sha):
        raise ValueError("更新目标提交无效，请先重新检查官方版本")
    settings = load_network_settings() if settings is None else settings
    sources = [(OFFICIAL_URL, settings.proxy, "官方 GitHub")]
    if settings.proxy != "direct":
        sources.append((OFFICIAL_URL, "direct", "官方 GitHub 直连"))
    if settings.mirror:
        sources.append((settings.mirror, "direct", "配置镜像（已核对官方提交）"))
    for index, (url, proxy, label) in enumerate(sources):
        timeout = _timeout(deadline, len(sources) - index, 60)
        if progress:
            progress(f"下载更新：{label.split('（')[0]}，尝试 {index + 1}/{len(sources)}")
        try:
            env = _git_environment(proxy, url)
            run_command(root, ["git", "fetch", "--no-tags", "--", url, f"refs/heads/{channel}"], timeout, env=env)
            sha = run_command(root, ["git", "rev-parse", "FETCH_HEAD"], _timeout(deadline, maximum=3), env=env)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
        if sha != trusted_sha:
            raise ValueError("下载提交与已核对的官方版本不一致，已停止更新；渠道或镜像可能已变化，请重新检查官方版本后重试")
        _timeout(deadline)
        return label
    raise ValueError("更新下载失败或超时；已尝试官方源及配置的备用源，请检查部署服务器代理与 HTTPS Git 镜像地址后重试")
