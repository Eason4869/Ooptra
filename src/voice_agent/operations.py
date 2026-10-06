"""Successful voice room operations, consumed after the room lock is released."""
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceOperation:
    kind: str
    source: str
    area: str
    channel: str
    visit_id: str
