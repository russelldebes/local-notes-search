"""Markdown-aware chunking.

Strategy:
  1. Strip YAML frontmatter (kept aside; tags/aliases could be used later).
  2. Walk the note line by line, tracking the current heading breadcrumb
     (e.g. "Projects > Notes-search > Design").
  3. Accumulate text within a heading section, then pack it into windows of
     ~max_chars with `overlap_chars` of overlap, breaking on paragraph
     boundaries where possible.
  4. Prepend the note title + breadcrumb to every chunk so each embedding
     carries its structural context (improves retrieval a lot).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    text: str          # the embeddable text, including its context header
    breadcrumb: str    # heading path within the note, for display
    chunk_index: int   # position within the note


def strip_frontmatter(content: str) -> str:
    return _FRONTMATTER_RE.sub("", content, count=1)


def _sections(content: str):
    """Yield (breadcrumb, body_text) for each heading section in order."""
    heading_stack: list[tuple[int, str]] = []  # (level, text)
    buf: list[str] = []
    crumb = ""

    def breadcrumb() -> str:
        return " > ".join(text for _, text in heading_stack)

    for line in content.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            if buf:
                yield crumb, "\n".join(buf).strip()
                buf = []
            level = len(m.group(1))
            title = m.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            crumb = breadcrumb()
        else:
            buf.append(line)

    if buf:
        yield crumb, "\n".join(buf).strip()


def _pack(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split a block into overlapping windows, preferring paragraph breaks."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    windows: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # Prefer to break on a paragraph, then a newline, then a space.
            for sep in ("\n\n", "\n", " "):
                cut = text.rfind(sep, start, end)
                if cut > start:
                    end = cut
                    break
        windows.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap_chars, start + 1)
    return [w for w in windows if w]


def chunk_note(title: str, content: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Turn one note's raw content into a list of context-aware chunks."""
    body = strip_frontmatter(content)
    chunks: list[Chunk] = []
    idx = 0
    for crumb, section_text in _sections(body):
        for window in _pack(section_text, max_chars, overlap_chars):
            header = f"Note: {title}"
            if crumb:
                header += f"\nSection: {crumb}"
            chunks.append(
                Chunk(
                    text=f"{header}\n\n{window}",
                    breadcrumb=crumb,
                    chunk_index=idx,
                )
            )
            idx += 1
    return chunks
