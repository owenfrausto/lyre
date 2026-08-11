from __future__ import annotations

import re
from typing import Any

_SPACE = re.compile(r"\s+")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def clean_text(value: Any, limit: int = 2_000) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = _SPACE.sub(" ", _CONTROL.sub("", _ANSI_ESCAPE.sub("", value))).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def title_from_prompt(prompt: str, limit: int = 72) -> str:
    if not prompt:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s", prompt, maxsplit=1)[0]
    if len(first_sentence) <= limit:
        return first_sentence
    return first_sentence[: limit - 1].rstrip() + "…"

