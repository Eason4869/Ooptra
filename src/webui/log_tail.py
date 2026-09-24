"""日志文件读取：文件列表、尾部读取与流式追加。"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

from core.logger_config import get_logger
from core.paths import LOG_FILE, LOGS_DIR

logger = get_logger("WebUILog")

DEFAULT_LOG_FILE = os.path.basename(LOG_FILE)
MAX_TAIL_LINES = 20000
_READ_CHUNK = 64 * 1024


def _read_tail_bytes(handle: Any, lines: int) -> bytes:
    """从文件末尾往前读，直到凑够 lines+1 个换行或到达文件头。"""
    handle.seek(0, os.SEEK_END)
    position = handle.tell()
    data = b""
    while position > 0 and data.count(b"\n") <= lines:
        size = min(_READ_CHUNK, position)
        position -= size
        handle.seek(position)
        data = handle.read(size) + data
    return data


def sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class LogTailer:
    """按需读取 logs 目录下的日志文件。"""

    def __init__(
        self,
        log_dir: str = LOGS_DIR,
        default_file: str = DEFAULT_LOG_FILE,
        *,
        poll_interval: float = 1.0,
    ) -> None:
        self.log_dir = str(log_dir)
        self.default_file = default_file
        self.poll_interval = max(0.2, float(poll_interval))

    def resolve(self, name: str | None) -> str:
        """把外部传入的文件名限制在 logs 目录内。"""
        candidate = os.path.basename(str(name or self.default_file).strip()) or self.default_file
        path = os.path.join(self.log_dir, candidate)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"日志文件不存在: {candidate}")
        return path

    def list_files(self) -> list[dict[str, Any]]:
        if not os.path.isdir(self.log_dir):
            return []
        items: list[dict[str, Any]] = []
        for entry in os.listdir(self.log_dir):
            path = os.path.join(self.log_dir, entry)
            if not os.path.isfile(path):
                continue
            if ".log" not in entry:
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            items.append({"name": entry, "size": stat.st_size, "mtime": stat.st_mtime})
        items.sort(key=lambda item: item["mtime"], reverse=True)
        return items

    def tail(self, name: str | None, lines: int) -> dict[str, Any]:
        path = self.resolve(name)
        count = max(1, min(int(lines), MAX_TAIL_LINES))
        with open(path, "rb") as handle:
            data = _read_tail_bytes(handle, count)
        text = data.decode("utf-8", errors="replace")
        return {
            "name": os.path.basename(path),
            "size": os.path.getsize(path),
            "lines": text.splitlines()[-count:],
        }

    async def stream(self, name: str | None, *, first_lines: int) -> AsyncIterator[str]:
        """先补发最近 first_lines 行，再持续追新；文件被轮转时自动重置。"""
        path = self.resolve(name)
        display = os.path.basename(path)
        count = max(1, min(int(first_lines), MAX_TAIL_LINES))

        with open(path, "rb") as handle:
            data = _read_tail_bytes(handle, count)
        tail_lines = data.decode("utf-8", errors="replace").splitlines()[-count:]
        yield sse("reset", {"name": display})
        for line in tail_lines:
            yield sse("line", {"line": line})

        offset = os.path.getsize(path)
        while True:
            await asyncio.sleep(self.poll_interval)
            if not os.path.exists(path):
                yield sse("reset", {"name": display, "reason": "日志文件已不存在"})
                return
            size = os.path.getsize(path)
            if size < offset:
                offset = 0
                yield sse("reset", {"name": display, "reason": "日志已轮转"})
            if size == offset:
                yield ": keep-alive\n\n"
                continue
            with open(path, "rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
            boundary = chunk.rfind(b"\n")
            if boundary < 0:
                yield ": keep-alive\n\n"
                continue
            offset += boundary + 1
            for line in chunk[: boundary + 1].decode("utf-8", errors="replace").splitlines():
                yield sse("line", {"line": line})


__all__ = ["LogTailer", "sse"]
