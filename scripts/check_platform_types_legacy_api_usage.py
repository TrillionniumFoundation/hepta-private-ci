#!/usr/bin/env python3
"""Reject removed platform.types APIs in tracked Rust consumers.

The check deliberately targets constructor chains returning ``Digest32``. It does
not flag ordinary ``str::as_bytes`` calls used as input to ``Digest32::of_bytes``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUST_ROOT = REPO_ROOT / "codex-rs"
REMOVED_DIGEST_BYTES = re.compile(
    r"Digest32::(?:of_bytes|new|from_array)\s*\([^;]{0,2048}?\)\s*\.as_bytes\s*\(\s*\)",
    flags=re.DOTALL,
)


def tracked_rust_files() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", "codex-rs/**/*.rs", "codex-rs/*.rs"],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"platform.types legacy API scan: cannot enumerate tracked files: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def main() -> int:
    if not RUST_ROOT.is_dir():
        print("platform.types legacy API scan: missing codex-rs", file=sys.stderr)
        return 2

    findings: list[str] = []
    files = tracked_rust_files()
    if not files:
        print("platform.types legacy API scan: no tracked Rust files found", file=sys.stderr)
        return 2

    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in REMOVED_DIGEST_BYTES.finditer(text):
            relative = path.relative_to(REPO_ROOT)
            findings.append(
                f"{relative}:{line_number(text, match.start())}: removed Digest32::as_bytes() receiver; "
                "use as_array() or into_array()"
            )

    if findings:
        print("platform.types legacy API scan: failed", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(f"platform.types legacy API scan: ok ({len(files)} tracked Rust files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
