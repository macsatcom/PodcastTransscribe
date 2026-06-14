"""Lightweight HTML utilities (no extra deps — stdlib only)."""

import html
import re
from html.parser import HTMLParser


class _TagStripper(HTMLParser):
    """Collects text nodes, discarding all tags and attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def strip_html(text: str | None) -> str:
    """Return *text* with all HTML tags removed and entities decoded.

    Collapses runs of whitespace (including newlines) to single spaces and
    strips leading/trailing whitespace.  Safe to call with None or "".
    """
    if not text:
        return ""

    # Pre-unescape so the parser sees clean entities (&amp; → &, etc.)
    text = html.unescape(text)

    stripper = _TagStripper()
    stripper.feed(text)
    raw = stripper.text()

    # Collapse whitespace
    return re.sub(r"\s+", " ", raw).strip()
