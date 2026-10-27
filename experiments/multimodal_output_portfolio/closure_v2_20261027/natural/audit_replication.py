"""Independent fixed-model replication audit without importing its scorer."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .audit_outputs import check_source, digest, edit_distance, load, normalized


def run(assets, experiment, first, output):
    manifest = load(assets / "MANIFEST.json")
    seal, result, rows = load(experiment / "FROZEN_REGISTRATION.json"), load(experiment / "RESULT.json"), load(experiment / "ROWS.json")
    check_source(manifest)
    documents = {r["id"]: r for r in manifest["documents"]}
    groups = [r["merchant_group"] for r in documents.values()]
    if len(set(groups)) != len(documents) or set(groups) & set(manifest["excluded_merchants"]):
        raise ValueError("Replication includes previous source groups")
    if seal["exact_N"] != manifest["actual_N"] or len(documents) != seal["exact_N"]:
        raise ValueError("Replication N was changed")
    enumeration = load(assets / "ENUMERATION_FROZEN.json")
    if digest(assets / "ENUMERATION_FROZEN.json") != manifest["enumeration_sha256"]:
        raise ValueError("Source enumeration identity differs")
    if not enumeration["registered_ns"] < manifest["registered_ns"] < seal["registered_ns"]:
        raise ValueError("Sources were not enumerated and frozen before inference")
    ordered_groups = [r["merchant_group"] for r in enumeration["ordered_candidates"]]
    if manifest["duplicate_images_excluded"] or groups != ordered_groups[:len(groups)]:
        raise ValueError("Observed replication did not use the first fixed source groups")
    if seal["ordered_source_ids"] != list(documents):
        raise ValueError("Frozen source order differs")
    workspace = assets.parents[1]
    historical = Path(__file__).resolve().parents[2] / "repair_20261026/natural/document/evidence/SOURCE_MANIFEST.json"
    previous = [historical, workspace / "natural-continuation-assets/document/MANIFEST.json",
        workspace / "natural-v2-assets/document/MANIFEST.json"]
    previous_hashes = {r["sha256"] for path in previous for r in load(path)["documents"]}
    if previous_hashes & {r["sha256"] for r in documents.values()}:
        raise ValueError("An exact image occurred in a prior experimental cohort")
    if digest(experiment / "FROZEN_MODEL.json") != digest(first / "FROZEN_MODEL.json"):
        raise ValueError("Model or selected threshold was changed after first qualification")
    choice = load(experiment / "FROZEN_MODEL.json")["choice"]
    if choice["regularization"] != 100. or choice["threshold"] != .1:
        raise ValueError("Original frozen parameter choice differs")
    grid, maximum, observed_fields = set(), 0., 0
    for row in rows:
        key = (row["id"], row["arm"], row["repetition"])
        if key in grid:
            raise ValueError("Duplicate replication row")
        grid.add(key)
        source = documents[row["id"]]
        directory = Path(row["output_directory"])
        answer = load(directory / "DELIVERED.json")
        if digest(directory / "DELIVERED.json") != row["answer_sha256"] or answer["answers"] != row["answers"]:
            raise ValueError("Actual replication answers differ")
        if digest(directory / "DELIVERED.jpg") != row["image_sha256"]:
            raise ValueError("Actual annotated image differs")
        with Image.open(directory / "DELIVERED.jpg") as image:
            image.load()
            if image.size != (source["image_size"]["width"], source["image_size"]["height"]):
                raise ValueError("Annotated replication image dimensions differ")
        quality, exact = [], []
        for field, reference in source["reference"].items():
            if reference is None or not normalized(field, reference):
                continue
            truth, emitted = normalized(field, reference), normalized(field, answer["answers"][field])
            equal = truth == emitted
            quality.append((equal + max(0., 1 - edit_distance(truth, emitted) / max(len(truth), len(emitted), 1))) / 2)
            exact.append(equal)
        if len(quality) != row["observed_reference_fields"] or answer["reference_received"]:
            raise ValueError("Missing-label or inference boundary differs")
        if not seal["registered_ns"] < row["delivered_ns"] < row["scored_ns"] or row["actual_OCR_calls"] != 1:
            raise ValueError("Replication chronology or compute differs")
        maximum = max(maximum, abs(float(np.mean(quality)) - row["quality"]),
            abs(float(np.mean(exact)) - row["field_exact"]),
            abs(float(np.mean(quality)) - .01 * row["cpu_seconds"] - row["cost_adjusted_return"]))
        if row["arm"] == "rule_residual" and row["repetition"] == 0:
            observed_fields += len(quality)
    expected = {(identity, arm, repetition) for identity in documents for arm in ("original_rules", "rule_residual") for repetition in (0, 1)}
    if grid != expected or maximum > 1e-10:
        raise ValueError("Replication output grid or score mismatch")
    metrics = ["quality", "field_exact", "cpu_seconds", "wall_seconds", "cost_adjusted_return"]
    differences = []
    for identity in sorted(documents):
        a = [r for r in rows if r["id"] == identity and r["arm"] == "rule_residual"]
        b = [r for r in rows if r["id"] == identity and r["arm"] == "original_rules"]
        if a[0]["answers"] != a[1]["answers"] or b[0]["answers"] != b[1]["answers"]:
            raise ValueError("Fixed-model repetition is not identical")
        differences.append([np.mean([r[key] for r in a]) - np.mean([r[key] for r in b]) for key in metrics])
    matrix = np.asarray(differences)
    rng = np.random.default_rng(2832)
    bootstrap = matrix[rng.integers(len(matrix), size=(5000, len(matrix)))].mean(1)
    intervals = np.quantile(bootstrap, [.0125, .9875], axis=0)
    max_statistics = 0.
    for index, metric in enumerate(metrics):
        reported = result["primary_contrast"][metric]
        max_statistics = max(max_statistics, abs(float(matrix[:, index].mean()) - reported["difference"]),
            float(np.max(np.abs(intervals[:, index] - reported["CI97_5"]))))
    if max_statistics > 1e-10 or bool(intervals[0, -1] > 0) != result["strong_rules_replication_gate_passed"]:
        raise ValueError("Replication confidence interval or acceptance differs")
    report = {"status": "passed", "imports_experiment_scorer_or_model": False,
        "actual_answer_image_pairs_reopened": len(rows), "independent_normalized_merchants": len(documents),
        "actual_OCR_calls": len(rows), "all_frozen_parameters_identical_to_first_qualification": True,
        "maximum_score_discrepancy": maximum, "maximum_interval_discrepancy": max_statistics,
        "observed_fields_per_repetition": observed_fields,
        "source_manifest_sha256": digest(assets / "MANIFEST.json"), "rows_sha256": digest(experiment / "ROWS.json"),
        "source_split_counts": manifest["upstream_split_counts"],
        "old24_result_not_pooled": True, "all_actual_sources_fixed_before_generation": True,
        "all_prior_cohort_exact_image_overlap": 0,
        "exact_enumerated_order_verified": True,
        "strong_rules_replication_gate_passed": result["strong_rules_replication_gate_passed"]}
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "experiment", "first", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.experiment, args.first, args.output)
