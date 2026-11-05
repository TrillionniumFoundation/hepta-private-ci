#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Freeze exact qualified source, binary, inputs and driver before native calls."""
import argparse
import datetime
import hashlib
import json
import pathlib


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(args):
    qualification = json.loads(args.qualification.read_text())
    if not qualification["all_passed"] or not qualification["source_unchanged"]:
        raise ValueError("source is not locally qualified")
    old = json.loads(args.qualification.with_name("SOURCE_MANIFEST.json").read_text())
    sources = {name: sha(args.root / name) for name in old}
    if any(value != old[name]["sha256"] for name, value in sources.items()):
        raise ValueError("source changed since qualification")
    manifest = json.loads((args.inputs / "INPUT_MANIFEST.json").read_text())
    if manifest["total_witness_rows"] != 21458 or len(manifest["fits"]) != 5:
        raise ValueError("incomplete witness collection")
    for item in manifest["files"]:
        if sha(args.inputs / item["name"]) != item["sha256"]:
            raise ValueError("input identity changed")
    drivers = sorted(path.name for path in pathlib.Path(__file__).parent.glob("*.py"))
    protocol = {"schema": "hepta-native-certificate-execution-v1",
        "frozen_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "binary_sha256": qualification["binary"]["sha256"], "native_sources": sources,
        "driver_sources": {name: sha(pathlib.Path(__file__).parent / name) for name in drivers},
        "input_manifest_sha256": sha(args.inputs / "INPUT_MANIFEST.json"),
        "qualification_sha256": sha(args.qualification),
        "required_fit_ids": [11, 23, 37, 53, 71], "required_total_rows": 21458,
        "acceptance": "Every source C bit, every exact scalar/vector and both verdicts equal independent Fraction; all declared controls reject or yield their declared non-proof result.",
        "source_semantics_reexecuted": False, "new_scientific_efficacy": False,
        "new_model_weights_or_task_evaluation": False,
        "limits": {"driver_cpu_seconds": 300, "native_cpu_seconds": 180, "address_space_bytes": 4*1024**3}}
    with args.output.open("x") as stream:
        json.dump(protocol, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"protocol_sha256": sha(args.output), "frozen_utc": protocol["frozen_utc"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("root", "qualification", "inputs", "output"):
        parser.add_argument("--"+name, type=pathlib.Path, required=True)
    main(parser.parse_args())
