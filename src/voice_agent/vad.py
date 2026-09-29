"""基于能量的简易 VAD：按帧判断是否有人在说话，并在静音后切出一句。"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class VadvConfig:
    sample_rate: int = 16000
    frame_ms: int = 30
    silence_ms: int = 700
    max_utterance_ms: int = 15000
    energy_threshold: float = 0.012  # 归一化 RMS 阈值，可按环境调


class EnergyVad:
    def __init__(self, config: VadvConfig | None = None) -> None:
        self.config = config or VadvConfig()
        self._buffer = bytearray()
        self._speaking = False
        self._silence_ms = 0
        self._utterance_ms = 0

    def reset(self) -> None:
        self._buffer.clear()
        self._speaking = False
        self._silence_ms = 0
        self._utterance_ms = 0

    @staticmethod
    def _rms(pcm16: bytes) -> float:
        if len(pcm16) < 2:
            return 0.0
        count = len(pcm16) // 2
        samples = struct.unpack("<" + "h" * count, pcm16[: count * 2])
        if not samples:
            return 0.0
        acc = 0.0
        for s in samples:
            v = s / 32768.0
            acc += v * v
        return (acc / count) ** 0.5

    def feed(self, pcm16: bytes) -> bytes | None:
        """喂入 PCM16 小段；若一句结束则返回完整 utterance 的 PCM，否则 None。"""
        if not pcm16:
            return None
        self._buffer.extend(pcm16)
        frame_bytes = int(self.config.sample_rate * self.config.frame_ms / 1000) * 2
        if frame_bytes <= 0:
            return None

        while len(self._buffer) >= frame_bytes:
            frame = bytes(self._buffer[:frame_bytes])
            del self._buffer[:frame_bytes]
            rms = self._rms(frame)
            active = rms >= self.config.energy_threshold

            if active:
                if not self._speaking:
                    self._speaking = True
                    self._silence_ms = 0
                    self._utterance_ms = 0
                    self._buffer.extend(frame)  # 保留起始帧
                    continue
                self._silence_ms = 0
            else:
                if not self._speaking:
                    continue
                self._silence_ms += self.config.frame_ms

            if self._speaking:
                self._utterance_ms += self.config.frame_ms
                if self._silence_ms >= self.config.silence_ms:
                    utt = bytes(self._buffer)
                    self.reset()
                    return utt or None
                if self._utterance_ms >= self.config.max_utterance_ms:
                    utt = bytes(self._buffer)
                    self.reset()
                    return utt or None
        return None
