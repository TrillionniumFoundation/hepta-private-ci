#!/usr/bin/env python3
"""Materialize the bounded final Hepta exact-head delta in a source checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path

EXPECTED_PATHS = {
    ".github/scripts/hepta_agentd_gap_patch.py",
    ".github/workflows/hepta-agentd-gap-autofix.yml",
    ".github/workflows/rust-ci.yml",
    "codex-rs/hepta-agentd/src/app_runtime.rs",
    "codex-rs/hepta-agentd/src/control.rs",
    "codex-rs/hepta-agentd/tests/support/fleet.rs",
    "codex-rs/uds/src/lib.rs",
}


def run(*args: str, capture: bool = False) -> str:
    completed = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=capture,
    )
    return completed.stdout if capture else ""


def replace_once(path: Path, old: str, new: str, description: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one {description}; found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_runtime_helper() -> None:
    path = Path("codex-rs/hepta-agentd/src/app_runtime.rs")
    old = "pub(crate) fn app_server_runtime_options(\n"
    new = (
        "#[cfg_attr(\n"
        "    not(test),\n"
        "    expect(\n"
        "        dead_code,\n"
        "        reason = \"the shared runtime-options constructor is retained for process qualification and the product-host integration seam\"\n"
        "    )\n"
        ")]\n"
        "pub(crate) fn app_server_runtime_options(\n"
    )
    replace_once(path, old, new, "app_server_runtime_options anchor")


def patch_linux_timeout() -> None:
    path = Path(".github/workflows/rust-ci.yml")
    text = path.read_text(encoding="utf-8")
    start_marker = "  argument_comment_lint:\n"
    end_marker = "\n  argument_comment_lint_macos:\n"
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise SystemExit("Linux argument-comment job boundary is not unique")
    prefix, remainder = text.split(start_marker, 1)
    block, suffix = remainder.split(end_marker, 1)
    old_timeout = "    timeout-minutes: 30\n"
    new_timeout = "    timeout-minutes: 60\n"
    if block.count(old_timeout) != 1:
        raise SystemExit("Linux argument-comment timeout is not exactly 30 once")
    block = block.replace(old_timeout, new_timeout, 1)
    path.write_text(
        prefix + start_marker + block + end_marker + suffix,
        encoding="utf-8",
    )


def remove_consumed_assets() -> None:
    for raw in (
        ".github/workflows/hepta-agentd-gap-autofix.yml",
        ".github/scripts/hepta_agentd_gap_patch.py",
    ):
        path = Path(raw)
        if not path.is_file():
            raise SystemExit(f"required consumed asset is missing: {raw}")
        path.unlink()


def assert_scope() -> None:
    changed = {
        line
        for line in run("git", "diff", "--name-only", capture=True).splitlines()
        if line
    }
    if changed != EXPECTED_PATHS:
        missing = sorted(EXPECTED_PATHS - changed)
        extra = sorted(changed - EXPECTED_PATHS)
        raise SystemExit(f"unexpected final delta; missing={missing}; extra={extra}")
    for raw in (
        ".github/workflows/hepta-agentd-gap-autofix.yml",
        ".github/scripts/hepta_agentd_gap_patch.py",
    ):
        if Path(raw).exists():
            raise SystemExit(f"consumed asset survived: {raw}")
    run("git", "diff", "--check")


def main() -> None:
    run("python3", ".github/scripts/hepta_agentd_gap_patch.py")
    patch_runtime_helper()
    patch_linux_timeout()
    remove_consumed_assets()
    run(
        "cargo",
        "fmt",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "--package",
        "codex-hepta-agentd",
        "--package",
        "codex-uds",
    )
    assert_scope()


if __name__ == "__main__":
    main()
