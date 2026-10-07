"""Fetch public image sources without sharing bot credentials or unbounded reads."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import warnings
from io import BytesIO
from urllib.parse import urljoin, urlsplit

import aiohttp
from PIL import Image as PILImage

MAX_IMAGE_BYTES = 16 * 1024 * 1024


def _public_address(host: str) -> bool:
    address = ipaddress.ip_address(host)
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_global


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("图片地址必须是无账号凭据的 HTTP/HTTPS 地址")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        if not _public_address(parsed.hostname):
            raise ValueError("图片地址必须指向 public 公网地址；本地图片请使用 Base64")
    return url


class PublicImageResolver(aiohttp.abc.AbstractResolver):
    """Validate the actual DNS answers used by the connector, including redirects."""

    def __init__(self):
        self._delegate = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        answers = await self._delegate.resolve(host, port, family)
        if not answers or any(not _public_address(answer["host"]) for answer in answers):
            raise ValueError("图片域名必须解析到 public 公网地址")
        return answers

    async def close(self):
        await self._delegate.close()


def _verify(payload: bytes) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
            with PILImage.open(BytesIO(payload)) as image:
                image.verify()
    except (OSError, ValueError, PILImage.DecompressionBombError, PILImage.DecompressionBombWarning) as exc:
        raise ValueError("下载内容不是有效图片或图片像素过大") from exc


async def download_image(url: str, *, max_bytes=MAX_IMAGE_BYTES, timeout=20.0) -> tuple[bytes, str]:
    validate_url(url)
    resolver = PublicImageResolver()
    connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, limit=2)
    try:
        async with aiohttp.ClientSession(
            connector=connector, cookie_jar=aiohttp.DummyCookieJar(), trust_env=False,
            auto_decompress=False, timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"Accept": "image/*", "Accept-Encoding": "identity"},
        ) as session:
            async def fetch():
                current = url
                for redirect_count in range(4):
                    validate_url(current)
                    async with session.get(current, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location or redirect_count == 3:
                                raise ValueError("图片地址重定向次数过多或目标无效")
                            current = urljoin(current, location)
                            continue
                        if response.status != 200:
                            raise ValueError(f"图片下载失败 HTTP {response.status}")
                        if response.content_length is not None and response.content_length > max_bytes:
                            raise ValueError("网络图片超过大小限制")
                        payload = bytearray()
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            if len(payload) + len(chunk) > max_bytes:
                                raise ValueError("网络图片超过大小限制")
                            payload.extend(chunk)
                        raw = bytes(payload)
                        await asyncio.to_thread(_verify, raw)
                        return raw, "image"
                raise ValueError("图片地址重定向次数过多")
            return await asyncio.wait_for(fetch(), timeout)
    except asyncio.TimeoutError:
        raise TimeoutError("网络图片下载超时") from None
    except aiohttp.ClientError:
        raise ValueError("图片下载失败，请检查图片地址与网络") from None
    finally:
        await connector.close()
        await resolver.close()
