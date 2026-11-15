"""Recompute the recorded calibration without training or model execution.

Checks raw-output hashes, full state digests, Q24 projections, labels, pair census
and exact reported aggregates. This is local custody verification, not external
authentication or an independent human audit of Reward A's classification.
"""

import argparse
import json
from pathlib import Path
import struct
import sys

from .neuron_calibration import OWNER_SOURCE_SHA256, SPEC_SHA256, canonical, completed_registration, sha, summarize


def verify(directory):
    registration = json.loads((directory / "registration.json").read_bytes())
    completion = json.loads((directory / "completion.json").read_bytes())
    report_bytes = (directory / "summary.json").read_bytes()
    report = json.loads(report_bytes)
    if (completion["state"] != "completed" or completion["rows"] != 128
            or completion["summary_sha256"] != sha(report_bytes)
            or sha((directory / "specification.json").read_bytes()) != SPEC_SHA256
            or sha((directory / "calibrator-source.py").read_bytes()) != registration["calibrator_source"]
            or registration["owner_source_sha256"] != OWNER_SOURCE_SHA256):
        raise ValueError("Completed calibration/source custody mismatch")
    rows = [json.loads(line) for line in (directory / "rows.jsonl").read_text().splitlines()]
    expected = summarize(rows)
    if any(report[key] != value for key, value in expected.items()):
        raise ValueError("Recomputed calibration differs from completed report")
    source_manifest = json.loads((directory / "source-manifest.json").read_bytes())
    excluded_ids, excluded_pixels = set(source_manifest["excluded_source_ids"]), set(source_manifest["excluded_pixel_hashes"])
    for row in rows:
        if excluded_ids.intersection(row["source_ids"]) or excluded_pixels.intersection(row["pixel_hashes"]):
            raise ValueError("Calibration source is not disjoint from excluded fit/probe ranges")
        model = row["generation_request"]["model"]
        if model["checkpoint_sha256"] != registration["checkpoint"] or model["source_sha256"] != OWNER_SOURCE_SHA256:
            raise ValueError("Row refers to a different selected model or source")
        for state in (row["previous_state"], row["current_state"]):
            payload = b"hepta.inference.generation-state.v1\0" + model["snapshot_sha256"].encode() + state["backend_state_sha256"].encode()
            payload += struct.pack("<i", -2 if state["plan_index"] is None else state["plan_index"])
            payload += b"".join(struct.pack("<I", v) for v in state["values_f32"])
            if sha(payload) != state["state_sha256"]:
                raise ValueError("Full latent state hash mismatch")
        for kind in ("image", "text"):
            relative = Path(row["output_paths"][kind])
            path = directory / relative
            if relative.is_absolute() or ".." in relative.parts or path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError("Raw output is outside the evidence directory")
            if sha(path.read_bytes()) != row["output_hashes"][kind]:
                raise ValueError("Raw output byte identity changed")
    return report, registration, rows


def native_fixture(directory, experiment, repository, destination):
    report, registration, rows = verify(directory)
    original = completed_registration(experiment)
    if original != registration["original"]:
        raise ValueError("Original completed experiment binding differs")
    # Fixed first verification pair; never select according to observed quality.
    row = next(row for row in rows if row["pair_index"] == 704)
    fixture = {"repository": str(repository.resolve()), "python": sys.executable,
               "artifact_root": str(experiment.resolve()), "checkpoint_name": "seed-17-terminal_entropic_ndu.pt",
               "model_id": "ndu-v6.seed17.terminal.neuron-pilot", "pins": row["generation_request"]["model"],
               "request": row["generation_request"], "previous_state": row["previous_state"],
               "expected_drive_q24": row["drive_q24"], "expected_prediction_q24": row["prediction_q24"],
               "expected_png_sha256": row["output_hashes"]["image"], "expected_text_sha256": row["output_hashes"]["text"],
               "calibration_directory": str(directory.resolve()), "specification_sha256": SPEC_SHA256,
               "calibration_summary_sha256": sha((directory / "summary.json").read_bytes()),
               "calibration_rows_sha256": sha((directory / "rows.jsonl").read_bytes())}
    with destination.open("x") as file:
        json.dump(fixture, file, indent=2, sort_keys=True, allow_nan=False)
        file.write("\n")
    return {"fixture_sha256": sha(destination.read_bytes()), "native_gate_expected": "InvalidCalibration",
            "measured_ece_ppm": report["native_measured_ece_ppm"], "measured_ood_far_ppm": report["native_measured_false_acceptance_ppm"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--repository", type=Path)
    args = parser.parse_args()
    if args.fixture:
        if not args.experiment or not args.repository:
            parser.error("--fixture also requires --experiment and --repository")
        result = native_fixture(args.directory, args.experiment, args.repository, args.fixture)
    else:
        report, _, _ = verify(args.directory)
        result = {"verified": True, "point_gates_passed": report["point_gates_passed"], "rows": 128}
    print(canonical(result).decode())
