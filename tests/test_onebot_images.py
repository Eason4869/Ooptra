import asyncio
import base64
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image as PILImage

from oopz_sdk.adapters.onebot.v11.adapter import OneBotV11Adapter
from oopz_sdk.adapters.onebot.v11.message import from_v11_message
from oopz_sdk.adapters.onebot.v11.types import make_user_source
from oopz_sdk.services.message import Message


def png_bytes():
    buffer = BytesIO()
    PILImage.new("RGB", (2, 3), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def wire_image(source, *, cq, url=""):
    if cq:
        escaped = source.replace("&", "&amp;").replace(",", "&#44;")
        return f"[CQ:image,file={escaped},url={url}]"
    return [{"type": "image", "data": {"file": source, "url": url}}]


@pytest.mark.parametrize("cq", [False, True])
@pytest.mark.parametrize("source_type", ["base64", "data", "file", "path"])
def test_onebot_image_uploads_actual_bytes(tmp_path, cq, source_type):
    payload = png_bytes()
    encoded = base64.b64encode(payload).decode("ascii")
    path = tmp_path / "image space.png"
    path.write_bytes(payload)
    source = {
        "base64": "base64://" + encoded,
        "data": "data:image/png;base64," + encoded,
        "file": path.as_uri(),
        "path": str(path),
    }[source_type]
    # Some senders include a URL alongside inline data; it must still be uploaded.
    parts = from_v11_message(wire_image(source, cq=cq, url="https://example.com/image.png"))
    upload = AsyncMock(return_value=SimpleNamespace(
        file_key="oopz-upload-key", url="https://oopz.example/upload.png",
        animated=False, display_name="image.png",
    ))
    service = object.__new__(Message)
    service._bot = SimpleNamespace(media=SimpleNamespace(upload_bytes=upload))
    text, attachments = asyncio.run(service._prepare_message_content("hello", *parts.parts))
    upload.assert_awaited_once()
    assert upload.call_args.args == (payload,)
    assert upload.call_args.kwargs["file_type"] == "IMAGE"
    assert upload.call_args.kwargs["ext"] == ".png"
    assert "oopz-upload-key" in text
    assert attachments[0]["fileKey"] == "oopz-upload-key"
    assert attachments[0]["width"] == 2 and attachments[0]["height"] == 3


@pytest.mark.parametrize("cq", [False, True])
def test_existing_oopz_attachment_remains_uploaded(cq):
    image = from_v11_message(wire_image("oopz-key", cq=cq, url="https://oopz.example/a.png")).parts[0]
    assert image.is_uploaded and image.file_key == "oopz-key"


@pytest.mark.parametrize("uri,expected", [
    ("file:///tmp/image%20space.png", "/tmp/image space.png"),
    ("file:///C:/Pictures/image%20space.png", "C:/Pictures/image space.png"),
    ("file://C:/Pictures/image.png", "C:/Pictures/image.png"),
])
@pytest.mark.parametrize("cq", [False, True])
def test_file_uri_keeps_absolute_path(uri, expected, cq):
    assert from_v11_message(wire_image(uri, cq=cq)).parts[0].file == expected


@pytest.mark.parametrize("target", ["group", "private"])
def test_astrbot_inline_image_is_uploaded_before_onebot_action_succeeds(tmp_path, target):
    async def run():
        payload = png_bytes()
        upload = AsyncMock(return_value=SimpleNamespace(
            file_key="uploaded-key", url="https://oopz.example/image.png",
            animated=False, display_name="image.png",
        ))
        service = object.__new__(Message)
        bot = SimpleNamespace(media=SimpleNamespace(upload_bytes=upload), messages=service)
        service._bot = bot
        service._config = SimpleNamespace(use_announcement_style=False)
        service.signer = SimpleNamespace(client_message_id=lambda: "client-id", timestamp_us=lambda: "123")
        service.open_private_session = AsyncMock(return_value=SimpleNamespace(session_id="session"))
        service._request_data = AsyncMock(return_value={"messageId": "sent-id", "timestamp": "123"})
        adapter = OneBotV11Adapter(bot, "bot-id", db_path=tmp_path / "ids.sqlite3")
        message = wire_image("base64://" + base64.b64encode(payload).decode("ascii"), cq=False)
        if target == "private":
            user_id = adapter.ids.createId(make_user_source("person-id")).number
            result = await adapter.send_private_msg({"user_id": user_id, "message": message})
            endpoint = "/im/session/v2/sendImMessage"
        else:
            result = await adapter.send_group_msg({
                "group_id": 123, "oopz_area_id": "area", "oopz_channel_id": "channel", "message": message,
            })
            endpoint = "/im/session/v2/sendGimMessage"
        assert result["message_id"] > 0
        upload.assert_awaited_once()
        assert service._request_data.call_args.args == ("POST", endpoint)
        sent = service._request_data.call_args.kwargs["body"]["message"]
        assert sent["attachments"][0]["fileKey"] == "uploaded-key"
    asyncio.run(run())


def test_invalid_inline_image_does_not_post_message():
    service = object.__new__(Message)
    upload = AsyncMock()
    service._bot = SimpleNamespace(media=SimpleNamespace(upload_bytes=upload))
    service._request_data = AsyncMock()
    parts = from_v11_message(wire_image("base64://not-an-image", cq=False)).parts
    with pytest.raises(ValueError, match="valid base64"):
        asyncio.run(service.send_message(*parts, area="area", channel="channel"))
    upload.assert_not_awaited()
    service._request_data.assert_not_awaited()
