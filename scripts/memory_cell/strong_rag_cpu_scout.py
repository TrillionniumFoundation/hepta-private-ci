"""Read-only BF16 hardware census on standard GitHub-hosted Linux machines.

A CPU feature observation is not a model result, runner reservation, or
future-host guarantee. This never stages weights, accesses test labels or trains.
"""

import argparse
import json
import os
import platform
import re
import sys
from pathlib import Path

from strong_rag_host_gate import assess
from strong_rag_resource_snapshot import write_snapshot

SCHEMA = "hepta.memory-strong-rag.host-scout.v1"
STANDARD_IMAGES = frozenset(("ubuntu-22.04", "ubuntu-24.04", "ubuntu-26.04"))


def census(cpuinfo, *, machine, runner_arch, image, source_commit):
    """Make an unsigned, bounded eligibility observation for one actual VM."""
    if image not in STANDARD_IMAGES:
        raise ValueError("standard hosted Ubuntu image required; never self-hosted")
    if not isinstance(source_commit, str) or not re.fullmatch(
        r"[0-9a-f]{40}", source_commit
    ):
        raise ValueError("exact source commit required")
    gate = assess(cpuinfo, machine=machine, runner_arch=runner_arch)
    return {
        "schema": SCHEMA,
        "source_commit": source_commit,
        "requested_hosted_runner": image,
        "hardware": gate,
        "eligible_cpu_for_unchanged_bf16_reader": gate["host_eligible"],
        "eligible_host_reserved": False,
        "same_hardware_on_next_run_guaranteed": False,
        "read_only_census": True,
        "weights_downloaded": False,
        "new_model_calls": 0,
        "training_executed": False,
        "independent_semantic_judge": False,
        "production_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux":
        raise ValueError("only actual Linux hosted-runner CPU information")
    result = census(
        Path("/proc/cpuinfo").read_text(encoding="utf-8"),
        machine=platform.machine(),
        runner_arch=os.environ.get("RUNNER_ARCH"),
        image=args.runner_image,
        source_commit=args.source_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(result, sort_keys=True))
    resources = write_snapshot(
        args.output.with_name(args.output.stem + "-resources.json"),
        source_commit=args.source_commit,
        runner_image=args.runner_image,
    )
    print(json.dumps(resources, sort_keys=True))
    # A completed scout is not a successful BF16-accelerated model experiment.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
