#!/usr/bin/env python3
"""Select frozen V12 source and exec the original complete Cell-v2 handoff.

The original independently pinned host configuration, runtime snapshot, model
material, resource limits and operation identity remain mandatory. This entry
creates no configuration, grant, qualification or replacement learning trial.
"""

import argparse
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hepta_smollm_execution_source_v1 as execution

PATHS = (
    "chain",
    "hepta",
    "source-parent",
    "source-materials",
    "output",
    "python",
    "cell-bin",
    "just",
    "hepta-target",
    "handoff-config",
    "runtime-snapshot",
)
FLAGS = frozenset("--" + name for name in PATHS) | {
    "--cache-max-bytes",
    "--cache-max-chunks",
    "--cache-max-manifests",
    "--cache-max-db-bytes",
    "--consumer-mode",
    "--handoff-config-sha256",
    "--runtime-snapshot-sha256",
}
ENTRY = "scripts/run_llm_cell_native_handoff.py"


def delegate(profile, arguments):
    """No new child owner: replace this coordinator with the original entry."""
    execution.require(profile == execution.PROFILE_V12, "explicit V12 handoff required")
    execution.require(
        type(arguments) is list
        and len(arguments) == 2 * len(FLAGS)
        and all(type(item) is str for item in arguments),
        "complete original handoff arguments required",
    )
    values = {}
    for flag, value in zip(arguments[::2], arguments[1::2]):
        execution.require(
            flag in FLAGS and flag not in values, "closed unique handoff flags"
        )
        values[flag] = value
    execution.require(
        set(values) == FLAGS, "complete original handoff arguments required"
    )
    execution.require(
        values["--consumer-mode"] == "cell-host-v2",
        "V12 cannot execute the original-v1 unavailable or legacy worker path",
    )
    execution.require(
        all(Path(values["--" + name]).is_absolute() for name in PATHS),
        "absolute original handoff paths required",
    )
    for flag in ("--handoff-config-sha256", "--runtime-snapshot-sha256"):
        execution.require(
            re.fullmatch(r"[0-9a-f]{64}", values[flag]),
            "exact original input pin required",
        )
    execution.require(
        Path(values["--hepta"]) == Path(__file__).resolve().parents[1],
        "handoff must retain this Hepta source checkout",
    )
    chain = Path(values["--chain"])
    execution.verify(chain, profile)
    execution.require(
        ENTRY in execution.checked_manifest(profile)["files"],
        "original handoff entry must belong to the frozen source closure",
    )
    # Do not reconstruct host configuration, capture a snapshot at load, round
    # budgets or introduce an intermediate Popen owner. The original entry
    # checks source_pins, snapshot and loader digest before native admission.
    os.execv(sys.executable, [sys.executable, "-B", str(chain / ENTRY), *arguments])
    raise RuntimeError("original handoff exec unexpectedly returned")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=(execution.PROFILE_V12,), required=True)
    parser.add_argument("handoff_arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    execution.require(
        args.handoff_arguments and args.handoff_arguments[0] == "--",
        "separate the complete original handoff arguments with --",
    )
    delegate(args.profile, args.handoff_arguments[1:])


if __name__ == "__main__":
    main()
