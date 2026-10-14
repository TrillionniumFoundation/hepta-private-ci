#!/usr/bin/env python3
"""Pure-Python, read-only paired evidence reviewer; never select a Stem.

It verifies the two research runners' cross-arm contracts and reported
probabilities but cannot authenticate model weights, no-change signatures,
chronology of predictions or independent real-world NDU outcomes.
"""
import argparse
import json
import re
from pathlib import Path

from compact_stem_trial import STEMS
from qualified_eval import (audit_dataset, brier_and_ece, digest, ood_results,
                            read_jsonl, strict_json_loads, validate_predictions)

SCHEMA = "hepta.compact-stem-paired-shadow-review.v1"
PROFILE = "hepta.compact-stem-head-only-shadow.v1"
ARMS = ("mmbert-small", "granite-97m-multilingual-r2")
BIND = ("dataset_digest", "scope_id", "shots", "steps", "batch_size", "seed",
        "head_kind", "head_parameter_ceiling", "actual_complete_trainable_head_parameters",
        "selected_train_case_digest", "training_minibatch_indices_sha256",
        "max_tokens_per_model", "device", "threads")


def sha256(value):
    return type(value) is str and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_manifest(path):
    data = strict_json_loads(Path(path).read_text(encoding="utf-8"))
    require(type(data) is dict, "invalid manifest object")
    return data


def check_arm(dataset, case_rows, arm_id, manifest_file, learned_file, frozen_file):
    spec = STEMS[arm_id]
    manifest = read_manifest(manifest_file)
    require(manifest.get("schema") == PROFILE and manifest.get("model_id") == arm_id
            and manifest.get("model_repository") == spec.repository
            and manifest.get("license") == spec.license
            and manifest.get("pooling") == spec.pooling
            and manifest.get("feature_width") == 384
            and manifest.get("feature_q24_rounded") is True,
            "Stem model, pooling, width or Q24 binding mismatch")
    revision = manifest.get("model_revision")
    require(type(revision) is str and bool(re.fullmatch(r"[0-9a-f]{40}", revision)),
            "floating or malformed model revision")
    for key in ("learned_head_sha256", "frozen_head_sha256", "learned_predictions_sha256",
                "frozen_predictions_sha256", "dataset_digest", "selected_train_case_digest",
                "training_minibatch_indices_sha256"):
        require(sha256(manifest.get(key)), "invalid artifact/selection digest: " + key)
    count, ceiling = (manifest.get("actual_complete_trainable_head_parameters"),
                      manifest.get("head_parameter_ceiling"))
    require(type(count) is int and type(ceiling) is int and ceiling in (2048, 8192, 16384)
            and 0 < count <= ceiling and type(manifest.get("trainable_encoder_parameters")) is int
            and manifest["trainable_encoder_parameters"] == 0
            and type(manifest.get("trainable_shared_projection_parameters")) is int
            and manifest["trainable_shared_projection_parameters"] == 0,
            "misstated trainable Head budget or trainable projection")
    require(manifest.get("scope_id") == case_rows[0]["scope_id"]
            and manifest.get("dataset_digest") == audit_dataset(dataset)["dataset_digest"]
            and manifest.get("authority") == "DENY_ALL"
            and manifest.get("production_promotion_permitted") is False
            and manifest.get("production_no_change_supplied") is False
            and manifest.get("independent_future_ndu_verified") is False
            and manifest.get("model_execution_is_research_backend_only") is True
            and manifest.get("publisher_weight_bytes_authenticated") is False
            and manifest.get("frozen_head_is_production_no_change") is False
            and manifest.get("cross_model_nontruncated_comparability") is True
            and type(manifest.get("truncated_cases")) is int
            and manifest["truncated_cases"] == 0,
            "untrusted authorization, mismatched dataset or truncated comparison")
    expected_encoder = digest([spec.repository, revision, spec.pooling,
                               manifest.get("max_tokens_per_model"), "l2->nearest-even-q24"])
    learned = read_jsonl(learned_file)
    frozen = read_jsonl(frozen_file)
    require(digest(learned) == manifest["learned_predictions_sha256"]
            and digest(frozen) == manifest["frozen_predictions_sha256"],
            "prediction packet hash mismatch")
    observed = []
    for rows, suffix, head in ((learned, "", "learned_head_sha256"),
                               (frozen, "/frozen-head", "frozen_head_sha256")):
        observed.append(validate_predictions(rows, case_rows))
        for row in rows:
            require(row.get("model_id") == arm_id + suffix
                    and row.get("model_revision") == revision
                    and row.get("encoder_digest") == expected_encoder
                    and row.get("head_digest") == manifest[head]
                    and row.get("runtime_generation") == 1
                    and row.get("status") == "Succeeded"
                    and sha256(row.get("shadow_feature_sha256"))
                    and row.get("execution_path") == "encoder_warm"
                    and row.get("backend_batch_size") == 1,
                    "prediction lacks expected immutable model/Head/feature binding")
    for key in observed[0]:
        require(observed[0][key]["shadow_feature_sha256"] ==
                observed[1][key]["shadow_feature_sha256"],
                "learned and frozen Head used different features")
    return manifest, observed[0], observed[1]


def compare(dataset, *, scope_id, task_id, mmbert_manifest, mmbert_learned,
            mmbert_frozen, granite_manifest, granite_learned, granite_frozen,
            no_change=None):
    audit = audit_dataset(dataset)
    require(type(scope_id) is str and bool(scope_id) and type(task_id) is str and bool(task_id),
            "Scope/task identity required")
    cases = [r for r in dataset if r["scope_id"] == scope_id and r["task_id"] == task_id]
    require(bool(cases) and {r["split"] for r in cases} ==
            {"train", "calibration", "test", "future", "ood"},
            "missing complete scoped evaluation cohort")
    a, al, af = check_arm(dataset, cases, ARMS[0], mmbert_manifest,
                          mmbert_learned, mmbert_frozen)
    b, bl, bf = check_arm(dataset, cases, ARMS[1], granite_manifest,
                          granite_learned, granite_frozen)
    for key in BIND:
        require(type(a.get(key)) is type(b.get(key)) and a.get(key) == b.get(key),
                "unfair paired model budget or matched-training drift: " + key)
    require(a["model_revision"] != b["model_revision"],
            "cross-family model revisions must be separately recorded")
    baseline = None
    if no_change is not None:
        baseline = validate_predictions(read_jsonl(no_change), cases)
    scores = {}
    for split in ("test", "future", "ood"):
        rows = [r for r in cases if r["split"] == split]
        scores[split] = {}
        for label, predictions in (("mmbert_learned", al), ("mmbert_frozen", af),
                                   ("granite_learned", bl), ("granite_frozen", bf),
                                   ("no_change", baseline)):
            scores[split][label] = brier_and_ece(rows, predictions) if predictions else None
        scores[split]["granite_minus_mmbert_accuracy"] = (
            scores[split]["granite_learned"]["accuracy"] -
            scores[split]["mmbert_learned"]["accuracy"])
        scores[split]["granite_minus_mmbert_brier"] = (
            scores[split]["granite_learned"]["brier"] -
            scores[split]["mmbert_learned"]["brier"])
    ood = {"mmbert_learned": ood_results(cases, al),
           "mmbert_frozen": ood_results(cases, af),
           "granite_learned": ood_results(cases, bl),
           "granite_frozen": ood_results(cases, bf)}
    if baseline is not None:
        ood["no_change"] = ood_results(cases, baseline)
    return {
        "schema": SCHEMA, "status": "retrospective_shadow_descriptive_only",
        "dataset_digest": audit["dataset_digest"], "scope_id": scope_id, "task_id": task_id,
        "matched_training_and_head_budget": True,
        "mmbert_revision": a["model_revision"], "granite_revision": b["model_revision"],
        "complete_head_parameters_each": a["actual_complete_trainable_head_parameters"],
        "no_change_independently_authenticated": False,
        "no_change_prediction_file_supplied": baseline is not None,
        "source_group_independence_attested": False,
        "future_predictions_sealed_before_outcomes": False,
        "publisher_weights_authenticated": False,
        "signed_future_ndu_verified": False,
        "target_host_resource_matched_and_attested": False,
        "production_worker_verified": False, "production_promotion_permitted": False,
        "research_winner_selected": False, "authority": "DENY_ALL",
        "metrics": scores, "ood_diagnostics": ood,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--task-id", required=True)
    for prefix in ("mmbert", "granite"):
        for suffix in ("manifest", "learned", "frozen"):
            parser.add_argument(f"--{prefix}-{suffix}", required=True)
    parser.add_argument("--no-change", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        raise FileExistsError("paired review cannot overwrite existing evidence")
    result = compare(read_jsonl(args.dataset), scope_id=args.scope_id, task_id=args.task_id,
                     mmbert_manifest=args.mmbert_manifest, mmbert_learned=args.mmbert_learned,
                     mmbert_frozen=args.mmbert_frozen, granite_manifest=args.granite_manifest,
                     granite_learned=args.granite_learned, granite_frozen=args.granite_frozen,
                     no_change=args.no_change)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"out": str(out), "production_promotion_permitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
