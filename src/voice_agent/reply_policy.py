"""Probability selection shared by automatic cascade and Live replies."""

import random
import time
import unicodedata
from collections.abc import Callable


def allow_reply(percent: int) -> bool:
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    return random.random() < percent / 100


def matches_force_keyword(text: str, keywords: list[str]) -> bool:
    def normalize(value: str) -> str:
        folded = unicodedata.normalize("NFKC", value).casefold()
        return "".join(char for char in folded if char.isalnum())

    normalized_text = normalize(text)
    return any(keyword and keyword in normalized_text for keyword in map(normalize, keywords))


class ConversationWindow:
    """Bounded member-specific follow-ups; unknown speakers never gain a window."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._deadlines: dict[str, float] = {}

    def clear(self) -> None:
        self._deadlines.clear()

    def observe(self, text: str, keywords: list[str], user_key: str, seconds: float) -> bool:
        named = matches_force_keyword(text, keywords)
        if seconds <= 0:
            self.clear()
            return named
        now = self._clock()
        self._deadlines = {key: value for key, value in self._deadlines.items() if value > now}
        active = bool(user_key and self._deadlines.get(user_key, 0) > now)
        if text.strip() and user_key and (named or active):
            if user_key not in self._deadlines and len(self._deadlines) >= 128:
                self._deadlines.pop(next(iter(self._deadlines)))
            self._deadlines[user_key] = now + seconds
        return named or active


def window_seconds(settings) -> float:
    return (max(1, min(300, settings.conversation_window_seconds))
            if settings.conversation_window_enabled else 0)
