#!/usr/bin/env python3
"""Make r8 readiness appendices exact, current and idempotent."""
from __future__ import annotations

from pathlib import Path

TARGET = Path("scripts/hepta-global-finalizer-r8.py")


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    marker = 'body = original.split(heading, 1)[0].rstrip()'
    if marker in text:
        return 0

    old = '''        document_path = ROOT / relative
        original = document_path.read_text(encoding="utf-8")
        if heading in original:
            continue
        appendix_lines = [
            heading,
            "",
            "This appendix records repository specification closure only. It does not "
            "grant runtime, model, provider, external-effect, operator, promotion or "
            "release authority.",
            "",
            "### Protocol bindings",
            "",
            *[f"- `{value}`" for value in protocols],
            "",
            "### Closed specification gaps",
            "",
            *[f"- `{value}`" for value in gap_ids],
            "",
        ]
        rendered = original.rstrip() + "\\n\\n" + "\\n".join(appendix_lines)
        document_path.write_text(rendered, encoding="utf-8")
        updated.append(
'''
    new = '''        document_path = ROOT / relative
        original = document_path.read_text(encoding="utf-8")
        body = original.split(heading, 1)[0].rstrip()
        appendix_lines = [
            heading,
            "",
            "This appendix records repository specification closure only. It does not "
            "grant runtime, model, provider, external-effect, operator, promotion or "
            "release authority.",
            "",
            "### Protocol bindings",
            "",
            *[f"- `{value}`" for value in protocols],
            "",
            "### Closed specification gaps",
            "",
            *[f"- `{value}`" for value in gap_ids],
            "",
        ]
        rendered = body + "\\n\\n" + "\\n".join(appendix_lines)
        if rendered == original:
            continue
        document_path.write_text(rendered, encoding="utf-8")
        updated.append(
'''
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r22 appendix precondition drift: old-count={count}")
    text = text.replace(old, new, 1)

    required = (
        marker,
        'rendered = body + "\\n\\n" + "\\n".join(appendix_lines)',
        "if rendered == original:",
        '*[f"- `{value}`" for value in protocols]',
        '*[f"- `{value}`" for value in gap_ids]',
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"r22 output missing required phrase: {phrase}")

    TARGET.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
