#!/usr/bin/env python3
"""Refreeze exact transferred Cell artifacts for an explicit runtime and device.

This creates a new candidate identity. It never promotes the original candidate's
observations into a new runtime/device qualification.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--runtime-pins", type=Path, required=True)
    args = parser.parse_args()
    root = args.bundle.resolve(strict=True)
    sources = json.loads((root / "SOURCE_MAP.json").read_text())
    for item in sources["files"]:
        path = (root / item["path"]).resolve(strict=True)
        if (
            not path.is_relative_to(root)
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("transferred source or artifact mismatch")
    sys.path.insert(0, str(root / "cells/scripts"))
    from hepta_cell_joint_worker import device, strict_json

    old = strict_json((root / "candidate/original_candidate.json").read_bytes())
    pins = strict_json(args.runtime_pins.read_bytes())
    required = {"source_commit", "source_tree", "binary_sha256", "config_sha256"}
    if (
        not required <= pins.keys()
        or pins["source_commit"] != old["source_bases"]["runtime"]
    ):
        raise ValueError("runtime identity does not match the frozen source choice")
    for key in ("binary_sha256", "config_sha256"):
        if (
            type(pins[key]) is not str
            or len(pins[key]) != 64
            or bytes.fromhex(pins[key]) == bytes(32)
        ):
            raise ValueError("invalid runtime digest")
    measured = device()
    if measured["numpy"] != old["device"]["numpy"]:
        raise ValueError(
            "install the frozen NumPy version in an isolated environment first"
        )
    value = {
        **old,
        "device": measured,
        "hia_root": str(root / "hia"),
        "runtime_identity": pins,
        "origin_candidate_sha256": sources["origin_candidate_sha256"],
        "runtime_execution": "new exact-source runtime/device candidate; actual execution still required",
    }
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    target = root / "candidate/candidate.json"
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        __import__("os").fsync(stream.fileno())
    print(
        json.dumps(
            {
                "candidate": str(target),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "device": measured,
                "transferred_files": len(sources["files"]),
            }
        )
    )


if __name__ == "__main__":
    main()
