"""Read-only peer of equal-boundary same-output speech timing correction."""

import argparse
import json
from pathlib import Path

from .peer_natural import close, paired, read, sha


def run(workspace, output):
    base = workspace / "natural-v2-runs/speech-qualification-001"
    run = workspace / "natural-v2-runs/speech-timer-correction-001"
    freeze = read(run / "FROZEN_REGISTRATION.json")
    result, rows = read(run / "RESULT.json"), read(run / "ROWS.json")
    original = {(r["id"], r["arm"], r["repetition"]): r for r in read(base / "ROWS.json")}
    for path, expected in freeze["input_pins"].items():
        if sha(path) != expected:
            raise ValueError("Timing correction changed a frozen scientific input")
    for record in freeze["source_files"]:
        if sha(Path(freeze["source_snapshot"]) / Path(record["path"]).name) != record["sha256"]:
            raise ValueError("Executed timing source changed")
    if sha(run / "ENCODER_MODEL.json") != sha(base / "ENCODER_MODEL.json"):
        raise ValueError("Timer measurement changed the encoder allocation policy")
    grid = set()
    for row in rows:
        key = (row["id"], row["arm"], row["repetition"])
        if key in grid:
            raise ValueError("Duplicated timing source/arm/repetition")
        grid.add(key)
        prior = original[key]
        path = Path(row["output_path"])
        raw = path.read_bytes()
        if sha(path) != prior["output_sha256"] or raw.decode("utf8").strip() != prior["transcript"]:
            raise ValueError("New timing output is not byte-identical to the original")
        if (path.parent / "FIRST.txt").read_bytes() != raw:
            raise ValueError("Initial-to-final text copy differs")
        public = read(path.parent / "PUBLIC_RESULT.json")
        if any(public[key] != row[key] for key in public):
            raise ValueError("Actual metadata readback disagrees with timing rows")
        if row["encoder"]["encoded_sha256"] != prior["encodings"][0]["encoded_sha256"] or row["beam"] != prior["generations"][0]["beam"]:
            raise ValueError("A changed representation or decoder choice was relabeled as a timing correction")
        if row["encoder_calls"] != 1 or row["decoder_calls"] != 1 or row["private_reference_received"]:
            raise ValueError("Measured policy computation differs")
        if row["metadata_start_monotonic_ns"] < row["timer_stop_monotonic_ns"]:
            raise ValueError("Metadata was inserted before the shared stop boundary")
        if row["metadata_inclusive_cpu_seconds"] < row["cpu_seconds"] or row["metadata_inclusive_wall_seconds"] < row["wall_seconds"]:
            raise ValueError("Deployment bookkeeping was not included in the extended timer")
    wanted = {key for key in original if key[1] in {"fixed_beam5", "encoder_gate"}}
    if grid != wanted or len(grid) != 256:
        raise ValueError("Correction grid changed or used new sources")
    comparisons = {}
    maximum = 0.
    for metric, recorded in result["encoder_minus_fixed_beam5"].items():
        independent = paired(rows, "encoder_gate", "fixed_beam5", metric, "speaker_id", 2821)
        maximum = max(maximum, close(independent["difference"], recorded["difference"]), close(independent["interval"], recorded["CI95"]))
        comparisons[metric] = independent
    old_quality = read(base / "RESULT.json")["encoder_vs_fixed_beam5"]
    close(old_quality["WER_difference"], result["same_output_original_WER_difference"])
    close(old_quality["WER_difference_CI95"], result["same_output_original_WER_difference_CI95"])
    shared = all(comparisons[key]["interval"][1] < 0 for key in ("cpu_seconds", "wall_seconds"))
    inclusive = all(comparisons[key]["interval"][1] < 0 for key in ("metadata_inclusive_cpu_seconds", "metadata_inclusive_wall_seconds"))
    if shared != result["corrected_shared_boundary_cost_gate_passed"] or inclusive != result["corrected_metadata_inclusive_cost_gate_passed"]:
        raise ValueError("Corrected timing gate differs")
    report = {"passed": True, "actual_text_outputs_and_metadata_reopened": 256,
        "all_original_transcript_bytes_encoder_hashes_and_beams_identical": True,
        "source_clusters": 16, "maximum_statistical_discrepancy": maximum,
        "independent_model_reruns": 0, "new_independent_quality_cohort": False,
        "same_function_core_timer_boundary_reviewed": "Both arms call the same function: audio preparation, fixed/public-gate beam selection, identical CT2 parameters, both transcript writes/readbacks/hash, then both stop timestamps before JSON serialization",
        "metadata_inclusive_boundary_reviewed": "Both arms then write and reopen the public JSON, and measure metadata-inclusive CPU/wall from the same original start",
        "shared_boundary_cost_gate": shared, "metadata_inclusive_cost_gate": inclusive,
        "comparisons": comparisons, "original_cheap_greedy_limit_unchanged": True,
        "original_registration_sha256": sha(base / "FROZEN_REGISTRATION.json"),
        "correction_registration_sha256": sha(run / "FROZEN_REGISTRATION.json"),
        "correction_rows_sha256": sha(run / "ROWS.json"), "correction_result_sha256": sha(run / "RESULT.json")}
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "comparisons"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.workspace, args.output)
