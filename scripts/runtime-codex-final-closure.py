#!/usr/bin/env python3
"""Final idempotent runtime.codex source-binding repairs.

This script is deliberately small and runs after all structural migrations so
qualification always binds the workspace toolchain that Cargo actually uses.
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


def main() -> None:
    replace_once(
        ROOT / "scripts/runtime-codex-qualification.py",
        '    "rust-toolchain.toml",\n',
        '    "codex-rs/rust-toolchain.toml",\n',
        "runtime.codex qualification toolchain binding",
    )


if __name__ == "__main__":
    main()
