#!/usr/bin/env python3
"""Final idempotent runtime.codex source-binding repairs.

This runs after all structural migrations. It binds qualification to the actual
workspace toolchain and keeps source-closure claims separate from pending
execution receipts.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one legacy occurrence")
        path.write_text(text.replace(old, new), encoding="utf-8")
        return
    if new in text:
        return
    raise RuntimeError(f"{marker}: expected legacy or migrated content")


def separate_qualification_pending(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if 'value["repositoryControlledGaps"] = []' in text and 'value["qualificationPending"]' in text:
        return
    begin = '    value["repositoryControlledGaps"] = [\n'
    start = text.find(begin)
    if start < 0:
        raise RuntimeError(f"{path.name}: repositoryControlledGaps assignment missing")
    end_marker = '    ]\n'
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{path.name}: repositoryControlledGaps terminator missing")
    end += len(end_marker)
    replacement = '''    value["repositoryControlledGaps"] = []
    value["qualificationPending"] = [
        "exact-head receipt for the final immutable map head",
        "deterministic current-main synthetic-merge receipt for the same source identity",
        "retained real-process crash, product E2E and strict-lint evidence",
    ]
'''
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def main() -> None:
    replace_once(
        ROOT / "scripts/runtime-codex-qualification.py",
        '    "rust-toolchain.toml",\n',
        '    "codex-rs/rust-toolchain.toml",\n',
        "runtime.codex qualification toolchain binding",
    )
    separate_qualification_pending(ROOT / "scripts/runtime-codex-finalize-map.py")
    separate_qualification_pending(
        ROOT / "scripts/runtime-codex-finalize-map-followup.py"
    )


if __name__ == "__main__":
    main()
