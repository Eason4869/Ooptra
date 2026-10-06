"""Probability selection shared by automatic cascade and Live replies."""

import random
import unicodedata


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
