"""Live 会话 WebSocket 连接：无代理走 websockets，有代理走 aiohttp。

``websockets<14`` 原生不支持 HTTP 代理；``aiohttp`` 是硬依赖且 ``ws_connect``
支持 ``proxy=``，因此代理场景统一换成 aiohttp，并对外暴露与 websockets
兼容的 ``send`` / ``__aiter__`` / ``close`` 最小接口。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class _AiohttpWs:
    """把 aiohttp 的 ClientWebSocketResponse 适配成 websockets 风格。"""

    def __init__(self, ws: Any, session: Any) -> None:
        self._ws = ws
        self._session = session

    async def send(self, data: str) -> None:
        await self._ws.send_str(data)

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str | bytes]:
        try:
            import aiohttp
        except ModuleNotFoundError:  # pragma: no cover
            aiohttp = None
        async for msg in self._ws:
            if aiohttp is not None and msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.ERROR,
            ):
                break
            data = getattr(msg, "data", msg)
            if isinstance(data, (bytes, str)):
                yield data

    async def close(self) -> None:
        try:
            await self._ws.close()
        finally:
            if self._session is not None:
                await self._session.close()


async def open_live_ws(
    url: str,
    *,
    proxy: str | None = None,
    max_size: int = 8 * 1024 * 1024,
) -> Any:
    """建立 Live WebSocket 连接。``proxy`` 为空则直连。"""
    if proxy:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30)
        session = aiohttp.ClientSession(timeout=timeout)
        try:
            ws = await session.ws_connect(
                url,
                proxy=proxy,
                max_msg_size=max_size,
                heartbeat=20,
            )
        except Exception:
            await session.close()
            raise
        return _AiohttpWs(ws, session)

    try:
        import websockets
    except ModuleNotFoundError as exc:
        raise RuntimeError("Live 后端需要 websockets：pip install websockets") from exc

    return await websockets.connect(
        url,
        max_size=max_size,
        ping_interval=20,
        ping_timeout=20,
    )


__all__ = ["open_live_ws"]
