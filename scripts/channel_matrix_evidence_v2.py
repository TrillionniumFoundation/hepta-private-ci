#!/usr/bin/env python3
"""Closed source and API-command inventory for channel.matrix qualification.

This is a thin policy overlay over channel_matrix_evidence.  It does not own a
second evidence format: every command and source snapshot is still emitted by
the canonical evidence implementation and consumed by its manifest verifier.
"""
from __future__ import annotations

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
)
API_COMPILE_FAIL_COMMAND = [
    "cargo",
    "test",
    "--locked",
    "-p",
    "codex-hepta-matrix-sdk",
    "--doc",
]

# Preserve the canonical implementation and extend only its closed inventories.
# dict.fromkeys retains deterministic order while rejecting accidental duplicate
# source entries.  Assigning on the imported module makes every canonical helper
# (snapshot, run, status manifest) use the same policy for this process.
evidence.SOURCE_ROOTS = tuple(
    dict.fromkeys((*evidence.SOURCE_ROOTS, *EXTRA_SOURCE_ROOTS))
)
if "api-compile-fail" in evidence.COMMANDS:
    raise RuntimeError("canonical evidence already defines api-compile-fail")
evidence.COMMANDS = {
    **evidence.COMMANDS,
    "api-compile-fail": API_COMPILE_FAIL_COMMAND,
}


def main() -> int:
    return evidence.main()


if __name__ == "__main__":
    raise SystemExit(main())
