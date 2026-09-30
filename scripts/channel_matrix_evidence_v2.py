#!/usr/bin/env python3
"""Closed source and command inventory for channel.matrix qualification.

This is a thin policy overlay over channel_matrix_evidence. It does not own a
second evidence format: every command and source snapshot is still emitted by
the canonical evidence implementation and consumed by its manifest verifier.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import channel_matrix_evidence as evidence

EXTRA_SOURCE_ROOTS = (
    "codex-rs/hepta-contracts",
    "codex-rs/hepta-operations",
    "codex-rs/state",
    "codex-rs/hepta-supervisor/src/matrix.rs",
    "codex-rs/hepta-matrixd/tests/fixtures/run-hermetic-synapse.sh",
    "tests/fixtures/run-hermetic-synapse.sh",
    ".github/workflows/channel-matrix-materialize.yml",
    ".github/workflows/channel-matrix-protected-production.yml",
)

# The exact candidate binds these transitive owners, so the same read-only
# receipt must execute their all-target build, native tests, strict lint and
# formatting rather than relying on transitive compilation alone.
OWNER_PACKAGES = (
    "codex-hepta-contracts",
    "codex-state",
    "codex-hepta-operations",
    "codex-hepta-matrix-protocol",
    "codex-hepta-matrix-store",
    "codex-hepta-matrix-sdk",
    "codex-hepta-matrixd",
)
OWNER_PACKAGE_ARGS = [
    item for package in OWNER_PACKAGES for item in ("-p", package)
]
COMPILE_COMMAND = [
    "cargo",
    "check",
    "--locked",
    *OWNER_PACKAGE_ARGS,
    "--all-targets",
]
API_COMPILE_FAIL_COMMAND = [
    "cargo",
    "test",
    "--locked",
    "-p",
    "codex-hepta-matrix-sdk",
    "--doc",
]
FOCUSED_GATE_COMMAND = [
    "python3",
    "../scripts/channel_matrix_focused_gate.py",
]
CLIPPY_COMMAND = [
    "cargo",
    "clippy",
    "--locked",
    "--no-deps",
    *OWNER_PACKAGE_ARGS,
    "--all-targets",
    "--",
    "-D",
    "warnings",
]
FORMAT_COMMAND = [
    "cargo",
    "fmt",
    *[
        item
        for package in OWNER_PACKAGES
        for item in ("--package", package)
    ],
    "--",
    "--check",
]

# Preserve the canonical implementation and extend only its closed inventories.
# dict.fromkeys retains deterministic order while rejecting accidental duplicate
# source entries. Assigning on the imported module makes every canonical helper
# (snapshot, run, status manifest) use the same policy for this process.
evidence.SOURCE_ROOTS = tuple(
    dict.fromkeys((*evidence.SOURCE_ROOTS, *EXTRA_SOURCE_ROOTS))
)
if "api-compile-fail" in evidence.COMMANDS:
    raise RuntimeError("canonical evidence already defines api-compile-fail")
for required in ("compile", "focused-tests", "clippy", "format"):
    if required not in evidence.COMMANDS:
        raise RuntimeError(f"canonical evidence lacks {required}")
evidence.COMMANDS = {
    **evidence.COMMANDS,
    "compile": COMPILE_COMMAND,
    "focused-tests": FOCUSED_GATE_COMMAND,
    "clippy": CLIPPY_COMMAND,
    "format": FORMAT_COMMAND,
    "api-compile-fail": API_COMPILE_FAIL_COMMAND,
}


def argument_value(flag: str) -> str | None:
    try:
        index = sys.argv.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(sys.argv):
        return None
    return sys.argv[index + 1]


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else None
    label = argument_value("--label")
    directory_value = argument_value("--directory")
    result = evidence.main()
    if result != 0:
        return result
    if command == "run" and label == "format":
        if directory_value is None:
            print(
                "FAIL_CHANNEL_MATRIX_REVIEW_SLICES: missing evidence directory",
                file=sys.stderr,
            )
            return 1
        try:
            import channel_matrix_review_slices as review

            directory = Path(directory_value)
            review.write_exclusive(
                directory / "review-slices.json",
                review.build(review.ROOT, directory, review.REGISTRY_PATH),
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            print(f"FAIL_CHANNEL_MATRIX_REVIEW_SLICES: {exc}", file=sys.stderr)
            return 1
        print("PASS_CHANNEL_MATRIX_REVIEW_SLICES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
