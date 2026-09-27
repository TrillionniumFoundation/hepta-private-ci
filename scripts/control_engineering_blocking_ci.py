#!/usr/bin/env python3
"""Idempotently wire control.engineering into the repository blocking fan-in."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".github/workflows/blocking-ci.yml"


def patched(text: str) -> str:
    permissions_old = "permissions:\n  contents: read\n"
    permissions_new = (
        "permissions:\n"
        "  contents: read\n"
        "  actions: read\n"
        "  pull-requests: read\n"
    )
    if permissions_new not in text:
        if text.count(permissions_old) != 1:
            raise ValueError("blocking_ci_permissions_anchor")
        text = text.replace(permissions_old, permissions_new, 1)

    job = (
        "  control-engineering:\n"
        "    name: control.engineering\n"
        "    uses: ./.github/workflows/control-engineering-required.yml\n"
        "    secrets: inherit\n\n"
    )
    required_anchor = "  required:\n"
    if job not in text:
        if text.count(required_anchor) != 1:
            raise ValueError("blocking_ci_required_anchor")
        text = text.replace(required_anchor, job + required_anchor, 1)

    needs_old = "    needs:\n      - scope\n      - hepta-contract-gate\n"
    needs_new = (
        "    needs:\n"
        "      - scope\n"
        "      - control-engineering\n"
        "      - hepta-contract-gate\n"
    )
    if needs_new not in text:
        if text.count(needs_old) != 1:
            raise ValueError("blocking_ci_needs_anchor")
        text = text.replace(needs_old, needs_new, 1)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "check"))
    args = parser.parse_args()
    current = TARGET.read_text(encoding="utf-8")
    expected = patched(current)
    changed = current != expected
    if args.command == "sync" and changed:
        TARGET.write_text(expected, encoding="utf-8")
    print(
        {
            "workflow": str(TARGET.relative_to(ROOT)),
            "changed": changed,
            "checkOnly": args.command == "check",
            "authorityGranted": False,
        }
    )
    if args.command == "check" and changed:
        raise SystemExit("FAIL_CONTROL_ENGINEERING_BLOCKING_CI_DRIFT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
