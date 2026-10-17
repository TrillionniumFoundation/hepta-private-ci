"""Independent model-free review of the scoped physical-fanout *accounting*.

Does not import the physical producer, issue an attestation, reopen model bytes,
or score natural language. Counts are process reported; no physical SLA claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SIZES = (64, 256, 1024, 4096)
SHAPE = "hepta.hdsi.granite97-fanout-unattested.v1"
HEAD_FIELDS = {"schema", "parent_source_plan_sha256", "model_repo", "model_revision",
               "model_sha256", "candidate", "source_case_ids", "source_digest_ids",
               "source_feature_keys", "cohorts",
               "total_wall_seconds", "total_cpu_seconds", "model_download_load_wall_seconds",
               "host_attested", "stem_winner_verified", "ndu_task_lift_verified",
               "natural_reasoning_verified", "future_holdout_verified", "production_authorized",
               "disposition"}
COHORT_FIELDS = {"fleet_size", "active_heads", "logical_borrows", "unique_inputs",
                 "distinct_encoded_inputs", "physical_encoder_batches",
                 "physical_encoder_sequences", "head_scalars", "head_weight_bytes_fp32",
                 "head_output_sha256", "scoped_feature_digest",
                 "metadata_circuit_parity_count", "cohort_wall_seconds",
                 "cohort_cpu_seconds", "feature_wall_seconds", "maxrss_bytes_process"}


class Denied(ValueError):
    pass


def require(ok, msg):
    if not ok:
        raise Denied(msg)


def _time(v):
    return type(v) in (int, float) and math.isfinite(v) and v >= 0


def review(source, manifest, receipt):
    """Requires the original parent source-owner envelope, NOT arbitrary input."""
    require(type(source) is dict and type(manifest) is dict and type(receipt) is dict,
            "untrusted envelope")
    require(set(receipt) == HEAD_FIELDS and receipt["schema"] == SHAPE, "receipt changed")
    require(source.get("schema") == "hepta.stem.optimal.original-source.v1"
            and source.get("heldout_labels_excluded") is True
            and source.get("production_authorized") is False
            and type(source.get("heldout")) is list and len(source["heldout"]) == 32,
            "original source custody absent")
    require(type(source.get("source_plan_sha256")) is str
            and receipt["parent_source_plan_sha256"] == source["source_plan_sha256"],
            "source receipt substitution")
    material = manifest.get("candidates", {}).get("granite97", {})
    require(manifest.get("research_only") is True
            and manifest.get("production_authorized") is False
            and manifest.get("precision") == "float32_cpu"
            and manifest.get("preprocessing") == "tokenizer_native_trunc128_masked_mean_l2",
            "material profile changed")
    require((receipt["candidate"], receipt["model_repo"], receipt["model_revision"],
             receipt["model_sha256"]) == ("granite97", material.get("repo"),
                                            material.get("revision"), material.get("weight_sha256")),
            "different model material")
    ids = [r["case_id"] for r in source["heldout"]]
    shas = [r["source_sha256"] for r in source["heldout"]]
    require(receipt["source_case_ids"] == ids and receipt["source_digest_ids"] == shas
            and len(set(shas)) == 32 and all(type(s) is str and re.fullmatch("[0-9a-f]{64}", s)
                                             for s in shas), "source not original")
    # Independently reconstruct scoped identity without importing the producer
    # or its feature bus. This checks consistent source-binding, not that a
    # genuine model forward occurred or that an input is semantically true.
    scope = {"principal": "original-public-test", "purpose": "hdsi-shadow",
             "generation": 1, "epoch": 0,
             "revocation": hashlib.sha256(b"hdsi-study-revocation-unattested").hexdigest(),
             "model_sha": material.get("weight_sha256"),
             "preprocess_sha": hashlib.sha256(manifest["preprocessing"].encode()).hexdigest()}
    expected_keys = []
    for text_sha in shas:
        payload = {"scope": scope, "modality": "text", "payload_sha256": text_sha}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode()
        expected_keys.append(hashlib.sha256(b"hepta.hdsi.feature.v1\0" + canonical).hexdigest())
    require(receipt["source_feature_keys"] == expected_keys,
            "source/feature key scope or preprocessing mismatch")
    require(type(receipt["cohorts"]) is list and len(receipt["cohorts"]) == 4,
            "incomplete scale panel")
    require(all(receipt[f] is False for f in
                ("host_attested", "stem_winner_verified", "ndu_task_lift_verified",
                 "natural_reasoning_verified", "future_holdout_verified", "production_authorized"))
            and receipt["disposition"] == "HOLD_NO_GO", "claim laundering")
    for key in ("total_wall_seconds", "total_cpu_seconds", "model_download_load_wall_seconds"):
        require(_time(receipt[key]), "untrusted process time")
    all_checks = []
    for n, row in zip(SIZES, receipt["cohorts"]):
        require(type(row) is dict and set(row) == COHORT_FIELDS, "unrecognized cohort fields")
        require(all(type(row[k]) is int for k in
                    ("fleet_size", "active_heads", "logical_borrows", "unique_inputs",
                     "distinct_encoded_inputs", "physical_encoder_batches",
                     "physical_encoder_sequences", "head_scalars", "head_weight_bytes_fp32",
                     "maxrss_bytes_process", "metadata_circuit_parity_count")), "invalid numeric counters")
        require((row["fleet_size"], row["active_heads"], row["logical_borrows"],
                 row["unique_inputs"], row["distinct_encoded_inputs"],
                 row["physical_encoder_batches"], row["physical_encoder_sequences"],
                 row["head_scalars"], row["head_weight_bytes_fp32"],
                 row["metadata_circuit_parity_count"]) ==
                (n, 32, n, 32, 32, 2, 32, n * 6914, n * 6914 * 4, 32),
                "claimed physical/logic accounting wrong")
        require(row["maxrss_bytes_process"] > 0 and all(_time(row[k]) for k in
                ("cohort_wall_seconds", "cohort_cpu_seconds", "feature_wall_seconds"))
                and row["feature_wall_seconds"] <= row["cohort_wall_seconds"],
                "invalid wall/CPU resource counters")
        for k in ("head_output_sha256", "scoped_feature_digest"):
            require(type(row[k]) is str and re.fullmatch("[0-9a-f]{64}", row[k]),
                    "invalid opaque tensor hash")
        all_checks.append({"fleet": n, "borrowers": n, "unique_features": 32,
                           "resident_head_fp32_bytes": n * 6914 * 4,
                           "claimed_batches_unattested": 32})
    return {"schema": "hepta.hdsi.fanout-accounting-review.v1",
            "original_source_independently_replayed": False,
            "scale_panel": all_checks, "trained_head_task_gain": None,
            "metadata_graph_only": True,
            "end_to_end_sla_verified": False, "pretrained_model_forward_attested": False,
            "production_authorized": False, "disposition": "HOLD_NO_GO"}


def verify_original_bytes(train: bytes, test: bytes, prepared: dict) -> None:
    # The original independent late-label auditor never calls model/trainer code.
    parent = Path(__file__).resolve().parents[1] / "stem-optimal-v1"
    sys.path.insert(0, str(parent))
    from stem_review_v1 import _source_reconstruct, FIXED_SHA
    require(prepared.get("publisher_sha256") == FIXED_SHA, "wrong independent publisher")
    train_rows, test_rows, _ = _source_reconstruct(train, test, FIXED_SHA)
    require(prepared.get("train") == train_rows and prepared.get("heldout") == test_rows,
            "source roster not independently reproduced")


def main():
    p = argparse.ArgumentParser()
    for k in ("source", "materials", "receipt", "original-train", "original-test", "output"):
        p.add_argument("--" + k, required=True)
    a = p.parse_args()
    prepared = json.loads(Path(a.source).read_text())
    verify_original_bytes(Path(a.original_train).read_bytes(),
                          Path(a.original_test).read_bytes(), prepared)
    result = review(prepared, json.loads(Path(a.materials).read_text()),
                    json.loads(Path(a.receipt).read_text()))
    result["original_source_independently_replayed"] = True
    data = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("xb") as f:
        f.write(data)
        f.flush()
    print(json.dumps({"review_sha256": hashlib.sha256(data).hexdigest(),
                      "disposition": "HOLD_NO_GO"}, sort_keys=True))


if __name__ == "__main__":
    main()
