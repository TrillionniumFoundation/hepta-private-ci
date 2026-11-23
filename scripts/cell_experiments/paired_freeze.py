"""Freeze a local coding candidate before taking delivery of the future panel.

With PYTHONPATH=scripts, run python -m cell_experiments.paired_freeze followed by
either "freeze SPEC MATERIALS SNAPSHOT" or "assemble SNAPSHOT FREEZE_SHA FUTURE REQUEST".

SPEC contains only parent, candidate, retention and timeout_seconds. FUTURE is
a JSON list of evaluation-only v1 confirmation records. Each command prints the
canonical digest of its new output. Have the authorized intake bind the freeze
digest before receiving B, then bind that same digest and the independently
timed B event to the assembled request digest. Files and local timestamps alone
cannot authenticate enrollment, prior access to a task or its arrival order.
"""

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from . import adoption, coding_sft, data, paired_cold

FREEZE_SCHEMA = "hepta.paired-cold.freeze.v1"
REQUEST_SCHEMA = "hepta.paired-cold.request.v1"
FIELDS = {"parent", "candidate", "retention", "timeout_seconds"}


def publish(value, output, *, check_request=False):
    """Validate staged bytes, then publish once without replacing an existing file."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    expected = data.digest(value)
    with TemporaryDirectory(dir=output.parent) as directory:
        staged = Path(directory) / "staged.json"
        coding_sft.write_new(staged, value)
        staged.chmod(0o600)
        if check_request:
            paired_cold.checked_request(staged, expected)
        else:
            adoption.require(
                data.digest(adoption.read_json(staged)) == expected,
                "staged freeze differs",
            )
        os.link(staged, output)
    return expected


def freeze(spec_path, materials, output):
    spec = adoption.read_json(spec_path)
    adoption.require(
        isinstance(spec, dict) and set(spec) == FIELDS,
        "freeze accepts only parent, candidate, retention and timeout_seconds",
    )
    timeout = spec["timeout_seconds"]
    adoption.require(type(timeout) is int and timeout > 0, "positive timeout required")
    parent, candidate = spec["parent"], spec["candidate"]
    paired_cold.checked_models(parent, candidate)
    paired_cold.checked_panels({"retention": spec["retention"]}, parent["runtime"])
    for manifest in (parent, candidate):
        adoption.require(
            coding_sft.verify_model(manifest, materials) == data.digest(manifest),
            "model inventory differs from disk",
        )
    return publish({"schema": FREEZE_SCHEMA, **spec}, output)


def assemble(snapshot_path, expected_freeze, future_path, output):
    snapshot = adoption.read_json(snapshot_path)
    adoption.require(
        isinstance(snapshot, dict)
        and set(snapshot) == FIELDS | {"schema"}
        and snapshot["schema"] == FREEZE_SCHEMA
        and data.digest(snapshot) == expected_freeze,
        "snapshot differs from the separately retained freeze digest",
    )
    future = adoption.read_json(future_path)
    adoption.require(isinstance(future, list) and future, "future list required")
    for record in future:
        data.validate_record(record, require_outcome=False)
        adoption.require(
            record["split"] == "confirmation"
            and record["authorization"]["training_allowed"] is False,
            "future data must be evaluation-only confirmation records",
        )
    request = {**snapshot, "schema": REQUEST_SCHEMA, "future": future}
    return publish(request, output, check_request=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    first = subparsers.add_parser("freeze")
    first.add_argument("spec", type=Path)
    first.add_argument("materials", type=Path)
    first.add_argument("snapshot", type=Path)
    second = subparsers.add_parser("assemble")
    second.add_argument("snapshot", type=Path)
    second.add_argument("freeze_sha")
    second.add_argument("future", type=Path)
    second.add_argument("request", type=Path)
    args = parser.parse_args()
    if args.operation == "freeze":
        print(freeze(args.spec, args.materials, args.snapshot))
    else:
        print(assemble(args.snapshot, args.freeze_sha, args.future, args.request))


if __name__ == "__main__":
    main()
