#!/usr/bin/env python3
"""Require structured duplicate-key classification in platform.wire JSON codecs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODECS = (
    ROOT / "codex-rs" / "hepta-wire" / "src" / "platform_types_json.rs",
    ROOT / "codex-rs" / "hepta-wire" / "src" / "platform_manifest_json.rs",
)
STRICT = ROOT / "codex-rs" / "hepta-wire" / "src" / "strict_json.rs"


def main() -> int:
    errors: list[str] = []
    if not STRICT.is_file():
        errors.append("missing codex-rs/hepta-wire/src/strict_json.rs")

    for path in CODECS:
        if not path.is_file():
            errors.append(f"missing {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        if 'contains("duplicate field")' in text:
            errors.append(
                f"{path.relative_to(ROOT)} classifies duplicate keys from parser error text"
            )
        if "strict_json::validate_json_structure" not in text:
            errors.append(
                f"{path.relative_to(ROOT)} does not invoke the structured JSON validator"
            )

    if errors:
        for error in errors:
            print(f"platform.types structured JSON gate: {error}", file=sys.stderr)
        return 1

    print("platform.types structured JSON gate: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
