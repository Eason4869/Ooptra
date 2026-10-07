import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from PIL import Image as PILImage

from oopz_sdk.adapters.onebot.v11.message import from_v11_message
from oopz_sdk.services.message import Message


def test_http_image_enters_upload_pipeline(monkeypatch):
    from oopz_sdk.utils import remote_image

    buffer = BytesIO()
    PILImage.new("RGB", (3, 4), "blue").save(buffer, format="PNG")
    payload = buffer.getvalue()
    download = AsyncMock(return_value=(payload, "image"))
    monkeypatch.setattr(remote_image, "download_image", download)
    upload = AsyncMock(return_value=SimpleNamespace(
        file_key="uploaded", url="https://oopz.example/image", animated=False, display_name="image",
    ))
    service = object.__new__(Message)
    service._bot = SimpleNamespace(media=SimpleNamespace(upload_bytes=upload))
    for wire in (
        [{"type": "image", "data": {"file": "https://images.example/picture.png"}}],
        "[CQ:image,file=https://images.example/picture.png]",
        [{"type": "image", "data": {"file": "previous-upload-key", "url": "https://images.example/picture.png"}}],
    ):
        parts = from_v11_message(wire).parts
        _, attachments = asyncio.run(service._prepare_message_content(*parts))
        assert attachments[0]["width"] == 3 and attachments[0]["height"] == 4
    assert download.await_count == 3 and upload.await_count == 3
    assert upload.call_args.args == (payload,)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://images.example/a", "http://127.0.0.1/a",
    "http://10.0.0.1/a", "http://[::1]/a", "http://169.254.169.254/a",
    "https://user:password@images.example/a",
])
def test_image_source_rejects_private_and_unsupported_urls(url):
    from oopz_sdk.utils.remote_image import validate_url

    with pytest.raises(ValueError):
        validate_url(url)


def test_dns_resolution_rejects_private_addresses(monkeypatch):
    from oopz_sdk.utils import remote_image

    async def run():
        resolver = remote_image.PublicImageResolver()
        monkeypatch.setattr(resolver._delegate, "resolve", AsyncMock(return_value=[{
            "hostname": "images.example", "host": "127.0.0.1", "port": 80,
            "family": 2, "proto": 0, "flags": 0,
        }]))
        try:
            with pytest.raises(ValueError, match="public"):
                await resolver.resolve("images.example", 80)
        finally:
            await resolver.close()
    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["valid", "redirect", "oversize", "stream", "timeout", "nonimage", "private_redirect", "loop"])
def test_remote_download_is_bounded_and_validated(monkeypatch, scenario):
    from oopz_sdk.utils import remote_image

    async def run():
        image = BytesIO()
        PILImage.new("RGB", (2, 3), "red").save(image, format="PNG")
        async def image_handler(request):
            return web.Response(body=image.getvalue(), content_type="image/png")
        async def redirect(request):
            raise web.HTTPFound("/image")
        async def oversize(request):
            return web.Response(body=b"x" * 1025)
        async def stream(request):
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(b"x" * 512)
            await response.write(b"x" * 513)
            await response.write_eof()
            return response
        async def timeout(request):
            await asyncio.sleep(.2)
            return await image_handler(request)
        async def nonimage(request):
            return web.Response(text="not an image")
        async def private_redirect(request):
            raise web.HTTPFound("http://127.0.0.1/private")
        async def loop(request):
            raise web.HTTPFound("/loop")
        app = web.Application()
        app.add_routes([web.get("/" + name, handler) for name, handler in {
            "image": image_handler, "valid": image_handler, "redirect": redirect,
            "oversize": oversize, "stream": stream, "timeout": timeout,
            "nonimage": nonimage, "private_redirect": private_redirect, "loop": loop,
        }.items()])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        # Redirect production public DNS to this controlled fixture only.
        async def fixture_resolve(self, host, port=0, family=0):
            return [{"hostname": host, "host": "127.0.0.1", "port": port,
                     "family": 2, "proto": 0, "flags": 0}]
        monkeypatch.setattr(remote_image.PublicImageResolver, "resolve", fixture_resolve)
        try:
            url = f"http://images.example:{port}/{scenario}"
            if scenario in {"valid", "redirect"}:
                payload, filename = await remote_image.download_image(url, max_bytes=1024)
                assert payload == image.getvalue() and filename == "image"
            elif scenario == "timeout":
                with pytest.raises(TimeoutError):
                    await remote_image.download_image(url, timeout=.03)
            else:
                with pytest.raises(ValueError):
                    await remote_image.download_image(url, max_bytes=1024)
        finally:
            await runner.cleanup()
    asyncio.run(run())
