"""Best-effort HTML -> readable plain text, used when an email has no
text/plain part (common for automated/marketing mail — sign-in notices,
billing alerts, etc. are frequently HTML-only). stdlib-only (no bs4/lxml
dependency) since this only needs to produce something readable, not a
faithful render.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "head", "title"}

# Cheap heuristic for "this looks like it's HTML markup, not prose" — used
# to repair messages that were already synced (and stored) before the
# imap_client fix below existed, without needing a DB migration.
_HTML_SNIFF_RE = re.compile(r"<!doctype\s+html|<html[\s>]|<body[\s>]|<head[\s>]", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        # Collapse the blank-line/whitespace noise that block-tag newlines
        # plus the original markup's own whitespace otherwise leaves behind.
        lines = [line.strip() for line in joined.splitlines()]
        collapsed: list[str] = []
        for line in lines:
            if line or (collapsed and collapsed[-1]):
                collapsed.append(line)
        return "\n".join(collapsed).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed markup shouldn't crash mail sync
        return re.sub(r"<[^>]+>", " ", html).strip()
    return parser.text()


def looks_like_html(text: str) -> bool:
    return bool(_HTML_SNIFF_RE.search(text[:1000]))
