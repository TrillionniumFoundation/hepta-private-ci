#!/usr/bin/env python3
"""Publish a complete cquery roster after validating its provider records."""

import re
import sys


LABEL = re.compile(r"//codex-rs/[^\s:]+:[^\s:]+")


def main() -> None:
    compatible = []
    incompatible = []
    seen = set()
    for raw in sys.stdin:
        line = raw.rstrip("\r\n")
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] not in {"compatible", "incompatible"}:
            raise ValueError("invalid configured Clippy target record")
        status, label = fields
        # An empty canonical repository denotes the same main repository.
        if label.startswith("@@//"):
            label = label[2:]
        if not LABEL.fullmatch(label) or label.startswith(
            ("//codex-rs/v8-poc:", "//codex-rs/v8-poc/")
        ):
            raise ValueError("configured Clippy target is outside the requested scope")
        if label in seen:
            raise ValueError("duplicate configured Clippy target")
        seen.add(label)
        if status == "compatible":
            compatible.append(label)
        else:
            incompatible.append(label)
    if not compatible:
        raise ValueError("configured Clippy target roster is empty")
    for label in sorted(incompatible):
        print(f"Bazel Clippy target is platform-incompatible: {label}", file=sys.stderr)
    # Bash reads this machine roster on Windows too; text stdout would emit CRLF.
    sys.stdout.buffer.write(
        "".join(f"{label}\n" for label in sorted(compatible)).encode("utf-8")
    )


if __name__ == "__main__":
    try:
        main()
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
