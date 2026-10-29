#!/usr/bin/env python3
"""Publish a complete cquery roster after validating its provider records."""

import argparse
import json
from pathlib import Path
import re
import sys


LABEL = re.compile(r"//codex-rs/[^\s:\"'\\\x00-\x1f\x7f]+:[^\s:\"'\\\x00-\x1f\x7f]+")


def checked_label(label: str) -> str:
    # An empty canonical repository denotes the same main repository.
    if label.startswith("@@//"):
        label = label[2:]
    if not LABEL.fullmatch(label) or label.startswith(
        ("//codex-rs/v8-poc:", "//codex-rs/v8-poc/")
    ):
        raise ValueError("Clippy target is outside the requested scope")
    return label


def loading_roster(path: Path) -> set[str]:
    labels = [
        checked_label(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    if not labels or len(labels) != len(set(labels)):
        raise ValueError("loading Clippy target roster is empty or duplicated")
    return set(labels)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--loading-expression", type=Path)
    mode.add_argument("--expected-labels", type=Path)
    args = parser.parse_args()
    if args.loading_expression is not None:
        labels = sorted(loading_roster(args.loading_expression))
        print(
            "config(set("
            + " ".join(json.dumps(label, ensure_ascii=False) for label in labels)
            + "), target)"
        )
        return
    expected = loading_roster(args.expected_labels) if args.expected_labels else None
    compatible = []
    incompatible = []
    seen = set()
    for raw in sys.stdin:
        line = raw.rstrip("\r\n")
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] not in {"compatible", "incompatible"}:
            raise ValueError("invalid configured Clippy target record")
        status, raw_label = fields
        label = checked_label(raw_label)
        if label in seen:
            raise ValueError("duplicate configured Clippy target")
        seen.add(label)
        if status == "compatible":
            compatible.append(label)
        else:
            incompatible.append(label)
    if expected is not None and seen != expected:
        raise ValueError("configured Clippy roster differs from the loading roster")
    if not compatible:
        raise ValueError("configured Clippy target roster is empty")
    for label in sorted(incompatible):
        print(f"Bazel Clippy target is platform-incompatible: {label}", file=sys.stderr)
    sys.stdout.write("".join(f"{label}\n" for label in sorted(compatible)))


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
