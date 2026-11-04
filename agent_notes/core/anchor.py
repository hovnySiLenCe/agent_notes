"""Re-find a quote inside text that may have changed since it was captured (pure functions, no platform code).

Accessible text differs from what the user saw in small ways: embedded-object placeholders (U+FFFC) where links or
inline elements sit, and whitespace that reflows. Matching therefore runs on a normalized copy (placeholders
dropped, whitespace runs collapsed) and maps the hit back to offsets in the original text. When the quote occurs
several times, the captured prefix/suffix context and the old offset pick the right occurrence.
"""
from __future__ import annotations

import re

OBJ = '￼'


def normalize(text: str, drop_space: bool = False) -> tuple[str, list[int]]:
    """(normalized text, index map): out[i] came from text[idx[i]]. idx has one extra entry = len(text).
    drop_space removes whitespace entirely (CJK text wraps without spaces, but copies may contain newlines)."""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        if ch == OBJ:
            continue
        if ch.isspace():
            if drop_space or (out and out[-1] == ' '):
                continue
            ch = ' '
        out.append(ch)
        idx.append(i)
    idx.append(len(text))
    return ''.join(out), idx


def _common_suffix(a: str, b: str) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _common_prefix(a: str, b: str) -> int:
    n = 0
    while n < len(a) and n < len(b) and a[n] == b[n]:
        n += 1
    return n


def find_all(text: str, quote: str) -> list[tuple[int, int]]:
    """Every occurrence of `quote` in `text` as (start, end) offsets into the original text.
    Whitespace runs match each other; if that finds nothing, whitespace is ignored altogether."""
    for drop in (False, True):
        nq = normalize(quote, drop)[0].strip()
        if not nq:
            return []
        nt, idx = normalize(text, drop)
        hits, i = [], nt.find(nq)
        while i >= 0:
            hits.append((idx[i], idx[i + len(nq) - 1] + 1))
            i = nt.find(nq, i + 1)
        if hits:
            return hits
    return []


def score(text: str, start: int, end: int, prefix: str = '', suffix: str = '') -> int:
    """How well the context around text[start:end] matches the captured prefix/suffix (characters agreeing)."""
    before = normalize(text[max(0, start - 3 * len(prefix) - 8):start])[0]
    after = normalize(text[end:end + 3 * len(suffix) + 8])[0]
    return _common_suffix(before.rstrip(), normalize(prefix)[0].rstrip()) + \
        _common_prefix(after.lstrip(), normalize(suffix)[0].lstrip())


def find_quote(text: str, quote: str, prefix: str = '', suffix: str = '', near: int | None = None
               ) -> tuple[int, int, int] | None:
    """Best occurrence of `quote` in `text` as (start, end, context score), or None."""
    best = None
    for s, e in find_all(text, quote):
        key = (score(text, s, e, prefix, suffix), -abs(s - near) if near is not None else 0)
        if best is None or key > best[0]:
            best = (key, s, e)
    return (best[1], best[2], best[0][0]) if best else None


def parts(quote: str) -> list[str]:
    """A multi-element selection is captured as the elements' texts joined by newlines
    (copied table rows: cells joined by tabs)."""
    return [p for p in (x.strip() for x in re.split(r'[\n\t]', quote)) if p]
