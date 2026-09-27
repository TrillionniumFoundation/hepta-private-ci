#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

SCRIPT = Path("scripts/apply-cognitive-types-stage1.py")
text = SCRIPT.read_text(encoding="utf-8")

old = '''def replace_once(text: str, old: str, new: str, path: str | Path) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)
'''
new = '''def replace_once(text: str, old: str, new: str, path: str | Path) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0:
        # Source formatters may change only whitespace around a guarded anchor.
        # Accept exactly one whitespace-normalized match; semantic drift still
        # fails closed because zero or multiple normalized matches are rejected.
        pieces = re.split(r"(\\s+)", old)
        pattern = "".join(r"\\s+" if piece.isspace() else re.escape(piece) for piece in pieces)
        updated, normalized_count = re.subn(pattern, lambda _: new, text, count=1)
        if normalized_count == 1:
            return updated
    raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
'''

if text.count(old) != 1:
    raise SystemExit("replace_once helper anchor changed; refusing to repair")
SCRIPT.write_text(text.replace(old, new, 1), encoding="utf-8")
