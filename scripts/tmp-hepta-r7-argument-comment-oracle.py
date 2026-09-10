#!/usr/bin/env python3
"""Align the r7 argument-comment repair oracle with repository canonical syntax."""

from pathlib import Path

path = Path("scripts/hepta-global-finalizer-r7.py")
text = path.read_text(encoding="utf-8")
replacements = (
    (
        '"walk_error_chain(error, /* depth */ 0, &mut |error| {",',
        '"walk_error_chain(error, /*depth*/ 0, &mut |error| {",',
    ),
    (
        '"Generation::new(/* value */ 1)?",',
        '"Generation::new(/*value*/ 1)?",',
    ),
)
for old, new in replacements:
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 1 and new_count == 0:
        text = text.replace(old, new, 1)
    elif old_count == 0 and new_count == 1:
        continue
    else:
        raise SystemExit(
            f"argument-comment oracle patch drift: old={old_count} new={new_count} marker={old!r}"
        )
path.write_text(text, encoding="utf-8")
