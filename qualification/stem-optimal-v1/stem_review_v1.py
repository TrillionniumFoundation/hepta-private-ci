"""Separate stdlib-only original publisher reviewer for the three candidate Stems.

No producer/trainer imports. Opens original public labels only after complete
raw prediction files have been written by distinct run jobs. It cannot sign
results, authenticate a hardware execution, or select a production model.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import unicodedata

FIXED_SHA = {
    "train": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
    "test": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d",
}
CATEGORIES = ("card_arrival", "cash_withdrawal_not_recognised", "exchange_rate", "lost_or_stolen_phone")
MODELS = ("granite47", "granite97", "mmbert140")
PROBS = ("frozen_init", "centroid", "learned")
PINNED_REV = "57ec275d8078af65b7731c2a98be812d844a6d6b"
CANDIDATE_SCHEMA = "hepta.stem.optimal.physical-unattested.v1"
SOURCE_SCHEMA = "hepta.stem.optimal.original-source.v1"


def _require(pred, why):
    if not pred:
        raise ValueError(why)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _norm(s):
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def _original_rows(blob: bytes, expect: str):
    _require(0 < len(blob) <= 2_000_000 and _sha(blob) == expect, "actual original public bytes changed")
    source = csv.DictReader(io.StringIO(blob.decode("utf-8", "strict")))
    _require(source.fieldnames == ["text", "category"], "publisher layout changed")
    mapping = {}
    for i, item in enumerate(source):
        _require(i < 20_000 and set(item) == {"text", "category"}, "malformed publisher row")
        text, category = item["text"], item["category"]
        _require(type(text) is str and 0 < len(text.encode("utf-8")) <= 4096 and type(category) is str, "publisher field bound")
        key = _norm(text)
        _require(bool(key), "empty pub source")
        if key in mapping:
            _require(mapping[key] == category, "inconsistent duplicate")
        mapping[key] = category
    return mapping


def _source_reconstruct(train_raw, test_raw, source_hashes):
    tr = _original_rows(train_raw, source_hashes["train"])
    te = _original_rows(test_raw, source_hashes["test"])
    expected_train = []
    expected_test = []
    private_gold = {}
    for which, data, target in (("train", tr, expected_train), ("heldout", te, expected_test)):
        n = 16 if which == "train" else 8
        for label, category in enumerate(CATEGORIES):
            eligible = [s for s in data if data[s] == category and (which == "train" or s not in tr)]
            eligible.sort(key=lambda s: _sha(("hepta-banking77-subset-v1\x00" + s).encode("utf-8")))
            _require(len(eligible) >= n, "original class sampling insufficient")
            for text in eligible[:n]:
                digest = _sha(text.encode("utf-8"))
                case_id = ("fit:" if which == "train" else "heldout:") + digest
                item = {"case_id": case_id, "source_sha256": digest, "text": text}
                if which == "train":
                    item["label"] = label
                else:
                    private_gold[case_id] = label
                target.append(item)
    for section in (expected_train, expected_test):
        section.sort(key=lambda row: _sha(("stem-optimal-order-v1\x00" + row["case_id"]).encode("utf-8")))
    return expected_train, expected_test, private_gold


def _validate_model_spec(material):
    _require(type(material) is dict and set(material) == {"schema", "precision", "preprocessing", "training", "candidates", "unresolved_controls", "research_only", "production_authorized"}, "invalid model materials")
    _require(material["schema"] == "hepta.stem.original-candidate-model-material.v1", "wrong model material schema")
    _require(material["training"] == {"seed": 17, "steps": 100, "learning_rate": 0.006, "per_cell_parameters": 6914, "cells": 4}, "unequal optimizer budgets")
    _require(material["precision"] == "float32_cpu" and material["preprocessing"] == "tokenizer_native_trunc128_masked_mean_l2", "unmatched representation")
    _require(set(material["candidates"]) == set(MODELS), "candidate roster incomplete")
    _require(material["research_only"] is True and material["production_authorized"] is False, "false authority")
    for name, spec in material["candidates"].items():
        _require(re.fullmatch("[0-9a-f]{40}", spec["revision"]) is not None and re.fullmatch("[0-9a-f]{64}", spec["weight_sha256"]) is not None and spec["width"] == 384, "material pin mismatch")


def _validate_predictions(run, source, material):
    _require(type(run) is dict and set(run) == {"schema", "candidate", "source_plan_sha256", "material_manifest_sha256", "model_repo", "model_revision", "actual_weight_sha256", "head_parameters", "optimizer_steps", "initial_head_sha256", "trained_head_sha256", "rows", "cost", "physical_claim_unattested", "future_windows_verified", "real_4096_cell_training_verified", "production_authorized", "disposition"}, "unsafe or label-bearing run fields")
    name = run["candidate"]
    _require(name in MODELS and run["schema"] == CANDIDATE_SCHEMA, "unknown candidate")
    _require(run["source_plan_sha256"] == source["source_plan_sha256"] and run["material_manifest_sha256"] == _sha(_json(material)), "source/material substitution")
    spec = material["candidates"][name]
    _require(run["model_repo"] == spec["repo"] and run["model_revision"] == spec["revision"] and run["actual_weight_sha256"] == spec["weight_sha256"], "false model material")
    _require(type(run["head_parameters"]) is int and run["head_parameters"] == 27656 and type(run["optimizer_steps"]) is int and run["optimizer_steps"] == 100, "nonidentical Head experiment")
    for h in ("initial_head_sha256", "trained_head_sha256"):
        _require(type(run[h]) is str and re.fullmatch("[0-9a-f]{64}", run[h]) is not None, "Head digest malformed")
    _require(run["initial_head_sha256"] != run["trained_head_sha256"], "unlearned optimizer")
    _require(run["physical_claim_unattested"] is True and run["future_windows_verified"] == 0 and run["real_4096_cell_training_verified"] is False and run["production_authorized"] is False and run["disposition"] == "HOLD_NO_GO", "research cannot mint authority")
    expected = {r["case_id"]: r["source_sha256"] for r in source["heldout"]}
    _require(type(run["rows"]) is list and len(run["rows"]) == len(expected) == 32, "missing original predictions")
    seen = set()
    for item in run["rows"]:
        _require(type(item) is dict and set(item) == {"case_id", "source_sha256", "scores"}, "unexpected producer case fields")
        ident = item["case_id"]
        _require(ident in expected and ident not in seen and item["source_sha256"] == expected[ident], "original case tampered/duplicated")
        seen.add(ident)
        _require(type(item["scores"]) is dict and set(item["scores"]) == set(PROBS), "incomplete original controls")
        for values in item["scores"].values():
            _require(type(values) is list and len(values) == 4 and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values) and abs(sum(values)-1) < 1e-5, "wrong/nonfinite probabilities")
    _require(seen == set(expected), "missing original source group")
    cost = run["cost"]
    _require(type(cost) is dict and set(cost) == {"encoder_forward_batches", "physical_encoder_sequences", "elapsed_wall_seconds", "elapsed_cpu_seconds", "head_train_wall_seconds", "model_download_load_wall_seconds", "feature_encode_wall_seconds", "maxrss_bytes", "energy_joules", "p99_latency_ms"}, "missing cost category")
    _require(type(cost["encoder_forward_batches"]) is int and cost["encoder_forward_batches"] == 6 and type(cost["physical_encoder_sequences"]) is int and cost["physical_encoder_sequences"] == 96, "fake claimed forward shape")
    for k in ("elapsed_wall_seconds", "elapsed_cpu_seconds", "head_train_wall_seconds", "model_download_load_wall_seconds", "feature_encode_wall_seconds"):
        _require(type(cost[k]) in (int, float) and math.isfinite(cost[k]) and cost[k] >= 0, "invalid cost observation")
    _require(type(cost["maxrss_bytes"]) is int and cost["maxrss_bytes"] > 0 and cost["energy_joules"] is None and cost["p99_latency_ms"] is None, "missing/false host meter")


def _exact_mcnemar(only_a: int, only_b: int):
    n = only_a + only_b
    if n == 0:
        return 1.0
    return min(1.0, 2.0 * sum(math.comb(n, j) for j in range(min(only_a, only_b) + 1)) / 2**n)


def _review(train_raw, test_raw, prepared, runs, material, *, source_hashes=FIXED_SHA):
    """Independent original scoring. Test overrides NEVER claim original verified."""
    _validate_model_spec(material)
    _require(type(prepared) is dict and set(prepared) == {"schema", "publisher_revision", "publisher_sha256", "train", "heldout", "heldout_labels_excluded", "research_only", "production_authorized", "source_plan_sha256"}, "unexpected source fields")
    _require(prepared["schema"] == SOURCE_SCHEMA and prepared["publisher_revision"] == PINNED_REV and prepared["publisher_sha256"] == source_hashes, "source version changed")
    _require(prepared["heldout_labels_excluded"] is True and prepared["research_only"] is True and prepared["production_authorized"] is False, "source authority false")
    _require(_sha(_json({k: v for k, v in prepared.items() if k != "source_plan_sha256"})) == prepared["source_plan_sha256"], "source plan unsealed")
    orig_train, orig_test, gold = _source_reconstruct(train_raw, test_raw, source_hashes)
    _require(prepared["train"] == orig_train and prepared["heldout"] == orig_test, "source selection not independently reproducible")
    _require(type(runs) is list and len(runs) == 3 and {r["candidate"] for r in runs} == set(MODELS), "all three physical jobs required")
    scored = {}
    for run in runs:
        _validate_predictions(run, prepared, material)
        by_id = {r["case_id"]: r["scores"] for r in run["rows"]}
        results = {}
        for arm in PROBS:
            correct, brier = 0, 0.0
            for case_id, actual in gold.items():
                values = by_id[case_id][arm]
                correct += int(max(range(4), key=lambda i: values[i]) == actual)
                brier += sum((p-(1.0 if idx == actual else 0.0))**2 for idx,p in enumerate(values))
            results[arm] = {"correct": correct, "n": 32, "mean_multiclass_brier": brier / 32}
        pairs = {}
        for compare in ("frozen_init", "centroid"):
            learned_only, baseline_only = 0, 0
            for case_id, y in gold.items():
                yes = max(range(4), key=lambda i: by_id[case_id]["learned"][i]) == y
                old = max(range(4), key=lambda i: by_id[case_id][compare][i]) == y
                learned_only += bool(yes and not old)
                baseline_only += bool(old and not yes)
            pairs[compare] = {"learned_only": learned_only, "baseline_only": baseline_only,
                              "nominal_exact_p": _exact_mcnemar(learned_only, baseline_only)}
        scored[run["candidate"]] = {"arms": results, "paired": pairs, "cost_observed_unattested": run["cost"]}
    return {"schema": "hepta.stem.optimal.independent-review.v1", "case_count": 32,
            "publisher_original_sha_verified": source_hashes == FIXED_SHA,
            "publisher_revision": PINNED_REV, "models": scored,
            "independent_publisher_label_recount": True, "training_continuation_future_windows": 0,
            "source_independent_families": 1, "trained_4096_cells": False,
            "matched_421m_total_lifecycle": False, "human_semantic_evaluation": False,
            "host_cost_attestation": False, "production_authorized": False,
            "stem_winner_verified": False, "ndu_benefit_verified": False,
            "disposition": "HOLD_NO_GO"}


def review_original(train_raw, test_raw, prepared, runs, material):
    return _review(train_raw, test_raw, prepared, runs, material, source_hashes=FIXED_SHA)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--train", required=True)
    p.add_argument("--test", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--materials", required=True)
    p.add_argument("--run", action="append", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = review_original(Path(args.train).read_bytes(), Path(args.test).read_bytes(),
                             json.loads(Path(args.source).read_text(encoding="utf-8")),
                             [json.loads(Path(x).read_text(encoding="utf-8")) for x in args.run],
                             json.loads(Path(args.materials).read_text(encoding="utf-8")))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("xb") as f:
        f.write(_json(result) + b"\n")
        f.flush()
    print(json.dumps({"score_sha256": _sha(out.read_bytes()), "authority": "DENY_ALL",
                      "publisher_original_verified": result["publisher_original_sha_verified"],
                      "disposition": result["disposition"]}, sort_keys=True))


if __name__ == "__main__":
    main()
