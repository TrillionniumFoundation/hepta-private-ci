"""Independent original-label scorer for registered hard-charge Stem cohort v3.

No producer/training imports or authority. A completed pretrained job only proves a
historical single-source physical canary, never time-disjoint utility or a winner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stem-optimal-v1"))
import stem_review_v1 as original

COHORT = "hard-charge-four-intents-v3"
SOURCE_SCHEMA = "hepta.stem.charge-stress.source.v3"
RUN_SCHEMA = "hepta.stem.charge-stress.physical-unattested.v3"
INTENTS = ("card_payment_fee_charged", "cash_withdrawal_charge",
           "exchange_charge", "transfer_fee_charged")
SALT = "hepta-stem-hard-charge-v3\x00"
ORDER = "hepta-stem-hard-charge-order-v3\x00"
SCORES = ("centroid", "frozen_init", "learned")
RECEIPT_FIELDS = {
    "schema", "cohort", "candidate", "source_plan_sha256",
    "material_manifest_sha256", "model_repo", "model_revision",
    "actual_weight_sha256", "initial_head_sha256", "trained_head_sha256",
    "head_parameters", "optimizer_steps", "rows", "cost",
    "publisher_future_windows", "matched_421m_lifecycle",
    "physical_claim_unattested", "production_authorized", "disposition", "authority",
}


def reconstruct(train_raw, test_raw, hashes):
    original._require(set(hashes) == {"train", "test"}, "publisher manifest keys")
    tr = original._original_rows(train_raw, hashes["train"])
    te = original._original_rows(test_raw, hashes["test"])
    expected, gold = {"train": [], "heldout": []}, {}
    for split, source, n in (("train", tr, 16), ("heldout", te, 8)):
        for label, category in enumerate(INTENTS):
            eligible = [text for text in source
                        if source[text] == category and (split == "train" or text not in tr)]
            eligible.sort(key=lambda text: original._sha((SALT + text).encode()))
            original._require(len(eligible) >= n, "publisher class coverage")
            for text in eligible[:n]:
                digest = original._sha(text.encode())
                cid = ("fit:" if split == "train" else "heldout:") + digest
                item = {"case_id": cid, "source_sha256": digest, "text": text}
                if split == "train":
                    item["label"] = label
                else:
                    gold[cid] = label
                expected[split].append(item)
    for split in expected:
        expected[split].sort(key=lambda row: original._sha((ORDER + row["case_id"]).encode()))
    return expected, gold


def _require_scores(values):
    original._require(type(values) is list and len(values) == 4 and
                      all(type(v) in (float, int) and math.isfinite(v)
                          and 0 <= v <= 1 for v in values) and
                      abs(sum(values) - 1.0) < 1e-5, "invalid original probabilities")


def _review(train_raw, test_raw, source, runs, materials, *, hashes=original.FIXED_SHA):
    original._validate_model_spec(materials)
    expected, gold = reconstruct(train_raw, test_raw, hashes)
    fields = {"schema", "cohort", "intents", "publisher_revision", "publisher_sha256",
              "train", "heldout", "heldout_labels_excluded", "research_only",
              "production_authorized", "source_plan_sha256"}
    original._require(type(source) is dict and set(source) == fields, "v3 source fields")
    original._require(source["schema"] == SOURCE_SCHEMA and source["cohort"] == COHORT
                      and source["intents"] == list(INTENTS)
                      and source["publisher_revision"] == original.PINNED_REV
                      and source["publisher_sha256"] == hashes, "different source/profile")
    original._require(source["heldout_labels_excluded"] is True
                      and source["research_only"] is True
                      and source["production_authorized"] is False,
                      "source authority/label leakage")
    original._require(source["train"] == expected["train"] and
                      source["heldout"] == expected["heldout"],
                      "original source cohort not independently reconstructed")
    original._require(original._sha(original._json({
        k: v for k, v in source.items() if k != "source_plan_sha256"
    })) == source["source_plan_sha256"], "v3 source digest")
    original._require(type(runs) is list and len(runs) == 3
                      and {r.get("candidate") for r in runs} == set(original.MODELS),
                      "all three original model receipts required")
    material_sha = original._sha(original._json(materials))
    results, heads = {}, set()
    for run in runs:
        original._require(type(run) is dict and set(run) == RECEIPT_FIELDS
                          and run["schema"] == RUN_SCHEMA and run["cohort"] == COHORT,
                          "unexpected/label-bearing original receipt")
        candidate = run["candidate"]
        model = materials["candidates"][candidate]
        original._require(run["source_plan_sha256"] == source["source_plan_sha256"]
                          and run["material_manifest_sha256"] == material_sha,
                          "cohort/model material substitution")
        original._require((run["model_repo"], run["model_revision"], run["actual_weight_sha256"])
                          == (model["repo"], model["revision"], model["weight_sha256"]),
                          "pretrained source mismatch")
        original._require(run["head_parameters"] == 27656 and run["optimizer_steps"] == 100,
                          "Head training budget mismatch")
        for key in ("initial_head_sha256", "trained_head_sha256"):
            original._require(type(run[key]) is str and
                              len(run[key]) == 64 and
                              all(ch in "0123456789abcdef" for ch in run[key]),
                              "Head material digest")
        original._require(run["initial_head_sha256"] != run["trained_head_sha256"],
                          "no trained checkpoint")
        heads.add(run["initial_head_sha256"])
        original._require(run["publisher_future_windows"] == 0 and
                          run["matched_421m_lifecycle"] is False and
                          run["physical_claim_unattested"] is True and
                          run["production_authorized"] is False and
                          run["disposition"] == "HOLD_NO_GO" and
                          run["authority"] == "DENY_ALL",
                          "research falsely promoted")
        cost = run["cost"]
        original._require(type(cost) is dict and set(cost) == {
            "physical_encoder_sequences", "encoder_forward_batches",
            "elapsed_wall_seconds", "elapsed_cpu_seconds",
            "model_download_load_wall_seconds", "feature_encode_wall_seconds",
            "head_train_wall_seconds", "maxrss_bytes", "energy_joules", "p99_latency_ms",
        }, "incomplete cost witness")
        original._require(type(cost["physical_encoder_sequences"]) is int
                          and cost["physical_encoder_sequences"] == 96 and
                          type(cost["encoder_forward_batches"]) is int
                          and cost["encoder_forward_batches"] == 6,
                          "missing true Encoder forward batch census")
        for key in ("elapsed_wall_seconds", "elapsed_cpu_seconds",
                    "model_download_load_wall_seconds", "feature_encode_wall_seconds",
                    "head_train_wall_seconds"):
            original._require(type(cost[key]) in (float, int)
                              and math.isfinite(cost[key]) and cost[key] > 0,
                              "invalid measured physical wall/CPU")
        original._require(type(cost["maxrss_bytes"]) is int and cost["maxrss_bytes"] > 0
                          and cost["energy_joules"] is None and cost["p99_latency_ms"] is None,
                          "unattested power/latency claim")
        original._require(type(run["rows"]) is list and len(run["rows"]) == 32,
                          "truncated heldout source")
        scored = {}
        by_id = {}
        for row in run["rows"]:
            original._require(type(row) is dict and set(row) == {
                "case_id", "source_sha256", "scores"
            }, "heldout label or unexpected field")
            cid = row["case_id"]
            original._require(cid in gold and cid not in by_id and
                              cid == "heldout:" + row["source_sha256"],
                              "swapped/duplicate heldout identity")
            original._require(type(row["scores"]) is dict and
                              set(row["scores"]) == set(SCORES), "missing cheap control")
            for v in row["scores"].values():
                _require_scores(v)
            by_id[cid] = row["scores"]
        original._require(set(by_id) == set(gold), "missing genuine heldout cases")
        for arm in SCORES:
            correct = sum(int(max(range(4), key=lambda i: by_id[cid][arm][i]) == y)
                          for cid, y in gold.items())
            brier = sum(sum((p - float(i == y)) ** 2
                            for i, p in enumerate(by_id[cid][arm]))
                        for cid, y in gold.items()) / 32
            scored[arm] = {"correct": correct, "n": 32, "mean_multiclass_brier": brier}
        paired = {}
        for arm in ("centroid", "frozen_init"):
            only_new = only_old = 0
            for cid, y in gold.items():
                new = max(range(4), key=lambda i: by_id[cid]["learned"][i]) == y
                old = max(range(4), key=lambda i: by_id[cid][arm][i]) == y
                only_new += int(new and not old)
                only_old += int(old and not new)
            paired[arm] = {"learned_only": only_new, "baseline_only": only_old,
                           "nominal_exact_p": original._exact_mcnemar(only_new, only_old)}
        results[candidate] = {"arms": scored, "paired": paired,
                              "cost_observed_unattested": cost}
    original._require(len(heads) == 1, "different Head initialization across Encoders")
    return {
        "schema": "hepta.stem.charge-stress.independent-review.v3",
        "cohort": COHORT, "publisher_original_sha_verified": hashes == original.FIXED_SHA,
        "independent_publisher_label_recount": True,
        "independent_label_reader": "original-publisher-second-process",
        "case_count": 32, "source_independent_families": 1,
        "future_windows": 0, "matched_421m_lifecycle": False,
        "head_and_centroid_comparable": True,
        "models": results,
        "stem_winner_verified": False, "ndu_benefit_verified": False,
        "production_authorized": False,
        "disposition": "HOLD_NO_GO", "authority": "DENY_ALL",
    }


def review_original(train_raw, test_raw, source, runs, materials):
    return _review(train_raw, test_raw, source, runs, materials, hashes=original.FIXED_SHA)


def main():
    p = argparse.ArgumentParser()
    for key in ("train", "test", "source", "materials", "output"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--run", action="append", required=True)
    args = p.parse_args()
    result = review_original(
        Path(args.train).read_bytes(), Path(args.test).read_bytes(),
        json.loads(Path(args.source).read_text()),
        [json.loads(Path(path).read_text()) for path in args.run],
        json.loads(Path(args.materials).read_text())
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as file:
        file.write(original._json(result) + b"\n")
        file.flush()
    print(json.dumps({"review_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "disposition": "HOLD_NO_GO", "authority": "DENY_ALL"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
