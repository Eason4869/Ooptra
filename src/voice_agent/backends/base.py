from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VoiceReply:
    user_text: str = ""
    text: str = ""  # assistant reply text
    pcm16: bytes = b""
    sample_rate: int = 24000
    user_key: str = ""
    raw: dict = field(default_factory=dict)


class VoiceBackend(ABC):
    """语音大脑：输入一段 utterance PCM，输出文字 + 回话 PCM。"""

    name: str = "base"

    @abstractmethod
    async def handle_utterance(
        self,
        pcm16: bytes,
        *,
        sample_rate: int,
        user_key: str = "",
        channel_key: str = "",
    ) -> VoiceReply:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None
