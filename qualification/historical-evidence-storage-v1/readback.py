#!/usr/bin/env python3
"""Verify preserved historical bytes and optionally restore their original paths."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPOSITORY / "qualification/cell-learning-loop-v1"))
from receipt_verifier import read_capture, verify_completed_receipt


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-dir", type=Path, help="Create a new directory containing the five original paths")
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name("ARCHIVE.json").read_bytes())
    for name, expected in manifest["original_identity_sources"].items():
        if identity(read_capture(REPOSITORY / name)) != expected:
            raise ValueError("Original identity source changed: " + name)
    originals, records = {}, []
    for member in manifest["members"]:
        name, archive_name = member["original_path"], member["archive_path"]
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or archive_name != name + ".gz"):
            raise ValueError("Invalid historical storage path")
        compressed = read_capture(REPOSITORY / archive_name)
        if identity(compressed) != member["archive"]:
            raise ValueError("Compressed archive differs: " + name)
        raw = read_capture(REPOSITORY / name)
        if identity(raw) != member["original"]:
            raise ValueError("Original bytes differ: " + name)
        json.loads(raw)
        originals[name] = raw
        records.append({"path": name, **identity(raw), "json_decoded": True})
    run = REPOSITORY / "qualification/cell-learning-loop-v1/evidence/run-20261106-001"
    phases = ["feedback", "evaluate", "revise_dependency"]
    for phase in phases:
        receipt = json.loads((run / "phase_results" / (phase + ".json")).read_bytes())
        verify_completed_receipt(run, phase, receipt)
    if args.restore_dir is not None:
        args.restore_dir.mkdir(exist_ok=False)
        for name, raw in originals.items():
            destination = args.restore_dir / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(raw)
    print(json.dumps({
        "schema": "hepta.historical-evidence.readback.v1",
        "original_commit": manifest["original_commit"],
        "archive_integrity": "VERIFIED",
        "members": records,
        "original_phase_receipts_verified": phases,
        "original_identity_sources_unchanged": True,
        "restored": args.restore_dir is not None,
        "qualification_decision": "HOLD",
        "historical_results_reclassified": False,
        "training_or_native_execution": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
