"""Review actual frozen-Stem/Head execution without inventing future NDU evidence.

Consumes the existing report, sealed predictions and original dataset. It does
not load weights, train Heads, attest a model/observer or emit a selection bundle.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from experiments.shared_stem_cell.wire import canonical, decode, sha, write_once

SCHEMA = "hepta.stem.physical-preflight.v1"
ARMS = ("linear", "gated", "low_rank", "sparse_expert")
SPLITS = ("holdout", "retention")
MAX_FILE_BYTES = 64 * 1024 * 1024


class PreflightError(ValueError):
    """Reject missing, contradictory or unpaired physical-study records."""


def require(ok: bool, why: str) -> None:
    if not ok:
        raise PreflightError(why)


def digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def checked_bytes(path: Path, expected: str | None = None) -> bytes:
    require(path.is_file() and not path.is_symlink(), "physical file missing or symlinked")
    size = path.stat().st_size
    require(0 < size <= MAX_FILE_BYTES, "unbounded or empty physical file")
    data = path.read_bytes()
    require(len(data) == size, "physical file changed while reading")
    if expected is not None:
        require(digest(expected) and sha(data) == expected, "physical file digest mismatch")
    return data


def probability(value: object, classes: int) -> list[float]:
    require(type(value) is list and len(value) == classes, "probability dimension drift")
    require(all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in value),
            "nonfinite or invalid probability")
    require(abs(math.fsum(value) - 1.0) <= 1e-5, "non-normalized prediction")
    return value


def review(manifest_path: Path, producer: Path, expected_report_sha256: str) -> dict:
    """Cross-check complete per-case physical records; never issue a NDU receipt."""
    manifest_raw = checked_bytes(manifest_path)
    plan = decode(manifest_raw)
    require(type(plan) is dict and plan.get("schema") == "hepta.shared-stem-execution.v1",
            "invalid execution plan")
    model = plan.get("model")
    require(type(model) is dict and model.get("kind") in ("encoder", "masked_lm")
            and type(model.get("revision")) is str and len(model["revision"]) == 40
            and all(c in "0123456789abcdef" for c in model["revision"])
            and type(model.get("files")) is dict and model["files"]
            and all(digest(v) for v in model["files"].values()),
            "unbound local Encoder manifest")
    classes = plan.get("classes")
    require(type(classes) is int and 2 <= classes <= 256, "invalid class count")
    dataset_binding = plan.get("dataset")
    require(type(dataset_binding) is dict and set(dataset_binding) == {"path", "sha256"}
            and digest(dataset_binding["sha256"]), "missing original dataset binding")
    dataset_rel = Path(dataset_binding["path"])
    require(not dataset_rel.is_absolute() and ".." not in dataset_rel.parts
            and len(dataset_rel.parts) >= 1, "dataset path escapes approved root")
    data = checked_bytes(manifest_path.parent / dataset_rel, dataset_binding["sha256"])
    report_raw = checked_bytes(producer / "report.json", expected_report_sha256)
    report = decode(report_raw)
    require(type(report) is dict and report.get("schema") == "hepta.shared-stem-executed.v1"
            and report.get("mode") == "local_pretrained"
            and report.get("production_accepted") is False
            and report.get("independent_evaluation") is False
            and report.get("manifest_sha256") == sha(manifest_raw)
            and digest(report.get("predictions_sha256"))
            and digest(report.get("source_sha256")), "invalid physical execution report")
    require(type(report.get("encoding")) is dict
            and report["encoding"].get("simulated_encoder") is False,
            "simulated Encoder is not a physical trial")
    predict_raw = checked_bytes(producer / "predictions.json", report["predictions_sha256"])
    packet = decode(predict_raw)
    require(type(packet) is dict and set(packet) == {"predictions"}
            and type(packet["predictions"]) is list, "invalid sealed prediction packet")
    original, groups_by_split = {}, {}
    for line in data.splitlines():
        require(bool(line), "blank dataset row")
        row = decode(line)
        require(type(row) is dict and set(row) == {
            "case_id", "group", "split", "observed_at", "cell", "scope", "text", "label"
        }, "physical dataset schema mismatch")
        key = row["case_id"]
        require(type(key) is str and key and key not in original,
                "invalid/duplicate source case")
        require(type(row["group"]) is str and row["group"]
                and type(row["scope"]) is str and row["scope"]
                and type(row["text"]) is str and row["text"]
                and type(row["cell"]) is int and row["cell"] >= 0
                and type(row["label"]) is int and 0 <= row["label"] < classes
                and row["split"] in ("train", "extra_train", "calibration", *SPLITS),
                "invalid original source case")
        before = groups_by_split.setdefault(row["group"], row["split"])
        require(before == row["split"], "group leakage across data splits")
        original[key] = row
    expected = {k: v for k, v in original.items() if v["split"] in SPLITS}
    require(bool(expected), "no held-out original cases")
    require(len({v["scope"] for v in original.values()}) == 1, "multiple scopes in physical study")
    seen, totals = set(), {}
    for p in packet["predictions"]:
        require(type(p) is dict and set(p) == {
            "case_id", "group", "split", "cell", "input_digest", "arm",
            "frozen_probabilities", "probabilities"
        }, "incomplete physical prediction")
        arm, case_id = p["arm"], p["case_id"]
        require(arm in ARMS and case_id in expected and (arm, case_id) not in seen,
                "missing/duplicate/foreign sealed prediction")
        case = expected[case_id]
        require(p["group"] == case["group"] and p["split"] == case["split"]
                and p["cell"] == case["cell"]
                and p["input_digest"] == sha(canonical([case["scope"], case["text"]])),
                "prediction source identity drift")
        seen.add((arm, case_id))
        learned = probability(p["probabilities"], classes)
        frozen = probability(p["frozen_probabilities"], classes)
        truth = case["label"]
        record = totals.setdefault((arm, case["split"]), [0, 0, 0, 0.0])
        record[0] += 1
        record[1] += int(max(range(classes), key=learned.__getitem__) == truth)
        record[2] += int(max(range(classes), key=frozen.__getitem__) == truth)
        record[3] += math.fsum((v - int(i == truth)) ** 2 for i, v in enumerate(learned))
    require(seen == {(arm, key) for arm in ARMS for key in expected},
            "incomplete physical Head/case prediction census")
    scores = []
    for (arm, split), counts in sorted(totals.items()):
        n, hits, frozen_hits, brier_sum = counts
        scores.append({"arm": arm, "split": split, "cases": n,
                       "accuracy": hits / n, "same_init_frozen_accuracy": frozen_hits / n,
                       "brier": brier_sum / n})
    reports = report.get("scores")
    require(type(reports) is list and len(reports) == len(scores), "incomplete producer score report")
    reported = {}
    for row in reports:
        require(type(row) is dict and set(row) == {
            "arm", "split", "cases", "accuracy", "same_init_frozen_accuracy", "brier",
            "independent_evaluation"
        } and row["independent_evaluation"] is False, "unqualified producer score")
        key = (row["arm"], row["split"])
        require(key not in reported, "duplicate producer score")
        reported[key] = row
    for score in scores:
        row = reported.get((score["arm"], score["split"]))
        require(row is not None and type(row["cases"]) is int and row["cases"] == score["cases"]
                and all(type(row[k]) in (int, float) and math.isfinite(row[k])
                        and abs(row[k] - score[k]) <= 1e-7
                        for k in ("accuracy", "same_init_frozen_accuracy", "brier")),
                "sealed predictions disagree with producer score")
    return {"schema": SCHEMA, "producer_report_sha256": sha(report_raw),
            "manifest_sha256": sha(manifest_raw), "dataset_sha256": sha(data),
            "predictions_sha256": sha(predict_raw), "producer_source_sha256": report["source_sha256"],
            "model_revision": model["revision"], "model_manifest_sha256": sha(canonical(model)),
            "observed_original_cases": len(original), "held_out_cases": len(expected),
            "head_arms": list(ARMS), "scores_recomputed_from_sealed_predictions": scores,
            "non_temporal_rows": sum(row["observed_at"] is None for row in original.values()),
            "unverified_independent_source_groups": True,
            "independent_outcome_evaluator_verified": False,
            "no_change_production_baseline_verified": False,
            "prospective_future_windows_verified": False,
            "target_host_e1_e6_resource_suite_verified": False,
            "ready_for_e1_e6_selection": False, "production_accepted": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--producer", required=True, type=Path)
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = review(args.manifest, args.producer, args.report_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_once(args.output, receipt)


if __name__ == "__main__":
    main()
