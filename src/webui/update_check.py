"""从 GitHub 检查 Ooptra 更新（只读，不自动升级）。"""

from __future__ import annotations

import re
import time
from typing import Any

from core.logger_config import get_logger
from core.version import RELEASE_BASE_VERSION, __version__

logger = get_logger("UpdateCheck")

GITHUB_REPO = "Eason4869/Ooptra"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_REPO}"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
DEFAULT_BRANCH = "main"


def _normalize_version(value: str) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("v"):
        text = text[1:]
    return text


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in _normalize_version(value).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def _is_newer(latest: str, current: str) -> bool:
    latest = _normalize_version(latest)
    current = _normalize_version(current)
    date_version = r"\d{6}(?:\.\d+)?-(?:beta|dev)"
    if re.fullmatch(date_version, current) and not re.fullmatch(date_version, latest):
        current = RELEASE_BASE_VERSION
    return _version_tuple(latest) > _version_tuple(current)


def _payload_base() -> dict[str, Any]:
    return {
        "current_version": __version__,
        "repo_url": GITHUB_REPO_URL,
        "default_branch": DEFAULT_BRANCH,
        "branch_url": f"{GITHUB_REPO_URL}/tree/{DEFAULT_BRANCH}",
        "releases_url": f"{GITHUB_REPO_URL}/releases",
        "checked_at": time.time(),
    }


async def check_github_update(proxy: str | None = None) -> dict[str, Any]:
    """查询 GitHub 最新 release / tag，与本地 ``core.version.__version__`` 比较。"""
    result = _payload_base()
    try:
        import aiohttp
    except ModuleNotFoundError as exc:
        result.update({"ok": False, "error": f"缺少 aiohttp：{exc}", "update_available": False})
        return result

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ooptra-updater/{__version__}",
    }
    timeout = aiohttp.ClientTimeout(total=12)
    latest = ""
    source = ""
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(
                f"{GITHUB_API}/releases/latest", proxy=proxy
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    latest = _normalize_version(str(data.get("tag_name") or data.get("name") or ""))
                    source = "release"
                    html_url = data.get("html_url")
                    if html_url:
                        result["release_url"] = str(html_url)
            if not latest:
                async with session.get(
                    f"{GITHUB_API}/tags?per_page=1", proxy=proxy
                ) as resp:
                    if resp.status == 200:
                        tags = await resp.json(content_type=None)
                        if isinstance(tags, list) and tags:
                            latest = _normalize_version(str((tags[0] or {}).get("name") or ""))
                            source = "tag"
            async with session.get(GITHUB_API, proxy=proxy) as resp:
                if resp.status == 200:
                    repo = await resp.json(content_type=None)
                    branch = str(repo.get("default_branch") or "").strip()
                    if branch:
                        result["default_branch"] = branch
                        result["branch_url"] = f"{GITHUB_REPO_URL}/tree/{branch}"
    except Exception as exc:
        logger.warning("检查更新失败: %s", exc)
        result.update({"ok": False, "error": f"检查更新失败：{exc}", "update_available": False})
        return result

    if not latest:
        result.update(
            {
                "ok": False,
                "error": "GitHub 未返回可用的版本号",
                "latest_version": "",
                "update_available": False,
            }
        )
        return result

    update_available = _is_newer(latest, __version__)
    result.update(
        {
            "ok": True,
            "latest_version": latest,
            "update_available": update_available,
            "source": source,
            "message": f"发现新版本 v{latest}" if update_available else f"已是最新版本（v{__version__}）",
        }
    )
    return result


__all__ = ["DEFAULT_BRANCH", "GITHUB_REPO_URL", "check_github_update"]
