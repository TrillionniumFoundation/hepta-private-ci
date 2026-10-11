#!/usr/bin/env python3
"""Join genuine no-change with frozen and prequential learned Cell predictions.

This consumes the EXISTING prequential_trial.py and resource_gate.py formats.
It cannot authenticate a no-change owner, independent NDU outcome, model
execution, genuine crash recovery, or production authorization. No model weights
are downloaded or run. Every prediction must have been sealed before its label.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random

from jina_v5 import sha256_record
from qualified_eval import audit_dataset, percentile, read_jsonl, write_json

WINDOWS = ("future_1", "future_2")
SCALES = (64, 256, 1024, 4096)
SCHEMA = "hepta.neuron-prequential-threeway-shadow-review.v1"


def require_sha(value, size=64):
    if not (isinstance(value, str) and len(value) == size and
            all(x in "0123456789abcdef" for x in value)):
        raise ValueError("missing immutable SHA identity")


def event_time(row):
    try:
        t = datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))
        if t.tzinfo is None:
            raise ValueError("no timezone")
        return t.astimezone(timezone.utc)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("future timestamp must be offset-aware") from exc


def valid_probs(probs, classes):
    if (not isinstance(probs, list) or len(probs) != classes or
            any(type(p) not in (int, float) or not math.isfinite(p)
                or not 0 <= p <= 1 for p in probs) or
            abs(sum(probs) - 1) > 1e-5):
        raise ValueError("invalid probability distribution")


def read_journal(raw):
    try:
        return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeError, ValueError) as exc:
        raise ValueError("malformed immutable prediction journal") from exc


def verify_and_index(dataset, trial, journal_bytes, nochange):
    audit = audit_dataset(dataset)
    if (trial.get("schema") != "hepta.jina-v5-cell-prequential-shadow.v1" or
            trial.get("production_promotion_permitted") is not False or
            trial.get("independent_ndu_signature_verified") is not False or
            trial.get("genuine_future_outcomes_authenticated") is not False or
            trial.get("dataset_audit", {}).get("dataset_digest") != audit["dataset_digest"]):
        raise ValueError("prequential trial incompatible with frozen dataset or research-only contract")
    require_sha(trial.get("revision"), 40)
    require_sha(trial.get("pre_label_prediction_journal_sha256"))
    if hashlib.sha256(journal_bytes).hexdigest() != trial["pre_label_prediction_journal_sha256"]:
        raise ValueError("pre-label prediction journal byte digest mismatch")
    records = trial.get("temporal_receipts")
    journal = read_journal(journal_bytes)
    futures = [r for r in dataset
               if r["split"] == "future" and r["task_id"] == trial["task_id"]]
    futures.sort(key=lambda row: (event_time(row), row["case_id"]))
    if not futures or len(futures) != len(journal) or len(futures) != len(records):
        raise ValueError("future Cell prediction/journal exact coverage missing")
    windows = defaultdict(list)
    per_group_windows = {}
    for row in futures:
        window = row.get("future_window")
        if window not in WINDOWS:
            raise ValueError("pre-registered future_1/future_2 window required")
        group = (row["scope_id"], row["group_id"])
        if group in per_group_windows and per_group_windows[group] != window:
            raise ValueError("same group appears in two future windows")
        per_group_windows[group] = window
        windows[window].append(row)
    if set(windows) != set(WINDOWS):
        raise ValueError("two future windows required")
    if max(event_time(row) for row in windows["future_1"]) >= min(
            event_time(row) for row in windows["future_2"]):
        raise ValueError("future windows are not strictly chronological")
    indexed = {}
    earliest_by_cell = set()
    initial = trial.get("initial_head_digests", {})
    for index, (row, record, prec) in enumerate(zip(futures, records, journal)):
        if type(record) is not dict or type(prec) is not dict:
            raise ValueError("malformed recorded prediction evidence")
        if (record.get("case_id") != row["case_id"] or
                prec.get("case_id") != row["case_id"] or
                record.get("event_order") != index or prec.get("event_order") != index or
                record.get("event_time") != row["event_time"] or
                prec.get("event_time") != row["event_time"] or
                record.get("scope_id") != row["scope_id"] or
                prec.get("scope_id") != row["scope_id"] or
                record.get("cell_id") != row.get("cell_id") or
                prec.get("cell_id") != row.get("cell_id")):
            raise ValueError("pre-label event identity/order mismatch")
        if (prec.get("outcome_included") is not False or
                "label" in prec or "answer" in prec or
                prec.get("production_promotion_permitted") is not False or
                record.get("outcome_label_revealed_after_prediction") is not True):
            raise ValueError("prediction journal leaked outcome or authority")
        check = dict(prec)
        seal = check.pop("record_digest", None)
        require_sha(seal)
        if (sha256_record(check) != seal or
                record.get("prediction_seal_before_label_update") != seal or
                record.get("preupdate_head_digest") != prec.get("head_digest") or
                prec.get("input_digest") != sha256_record(
                    [row["state"], row["question"], row["options"]]) or
                prec.get("probabilities") != record.get("trained_probabilities")):
            raise ValueError("tampered prediction precommit or unbound weights/input")
        require_sha(prec["head_digest"])
        require_sha(record.get("postupdate_head_digest"))
        classes = len(row["options"])
        valid_probs(record["trained_probabilities"], classes)
        valid_probs(record["frozen_same_initialization_probabilities"], classes)
        key = (row["scope_id"], row["cell_id"])
        initial_key = str(key)
        if initial_key not in initial:
            raise ValueError("missing frozen same-initialization Cell Head")
        require_sha(initial[initial_key])
        if key not in earliest_by_cell:
            if (prec["head_digest"] != initial[initial_key] or
                    any(abs(a - b) > 1e-6
                        for a, b in zip(record["trained_probabilities"],
                                        record["frozen_same_initialization_probabilities"]))):
                raise ValueError("initial learned/frozen Head mismatch before first update")
            earliest_by_cell.add(key)
        indexed[row["case_id"]] = {
            "dataset": row,
            "trained": record["trained_probabilities"],
            "frozen": record["frozen_same_initialization_probabilities"],
        }
    if trial.get("pre_label_prediction_journal_event_count") != len(futures):
        raise ValueError("wrong committed prediction count")
    if type(nochange) is not list or len(nochange) != len(futures):
        raise ValueError("genuine production no-change prediction coverage missing")
    observed, nochange_identity = set(), None
    for receipt in nochange:
        case_id = receipt.get("case_id")
        if case_id not in indexed or case_id in observed:
            raise ValueError("duplicate, wrong or missing no-change case")
        row = indexed[case_id]["dataset"]
        if (receipt.get("scope_id") != row["scope_id"] or
                receipt.get("model_id") != "no-change" or
                receipt.get("status") != "Succeeded" or
                receipt.get("dataset_digest") != audit["dataset_digest"] or
                receipt.get("input_digest") != sha256_record(
                    [row["state"], row["question"], row["options"]])):
            raise ValueError("no-change source/owner input binding mismatch")
        if any(name in receipt for name in ("label", "outcome",
                                           "external_ndu_utility", "total_cost")):
            raise ValueError("no-change prediction cannot assert independently observed outcome")
        require_sha(receipt.get("model_revision"), 40)
        require_sha(receipt.get("weights_digest"))
        if type(receipt.get("generation")) is not int or receipt["generation"] <= 0:
            raise ValueError("missing no-change runtime generation")
        valid_probs(receipt.get("probabilities"), len(row["options"]))
        identity = (receipt["model_revision"], receipt["weights_digest"],
                    receipt["generation"])
        if nochange_identity is not None and identity != nochange_identity:
            raise ValueError("no-change baseline changed during future window")
        nochange_identity = identity
        indexed[case_id]["no_change"] = receipt["probabilities"]
        observed.add(case_id)
    if set(indexed) != observed:
        raise ValueError("missing no-change predictions")
    return indexed, audit, nochange_identity


def measure(probs, correct_index):
    winner = max(range(len(probs)), key=lambda i: probs[i])
    return (float(winner == correct_index),
            sum((p - float(i == correct_index)) ** 2
                for i, p in enumerate(probs)) / len(probs))


def window_bootstrap(rows, *, control, seed, replicates, alpha=.05 / 8):
    clusters = defaultdict(list)
    for record in rows:
        item = record["dataset"]
        a = measure(record["trained"], item["label"])
        b = measure(record[control], item["label"])
        clusters[(item["scope_id"], item["group_id"])].append(
            (a[0] - b[0], a[1] - b[1]))
    pairs = [tuple(sum(p[k] for p in values) / len(values)
                   for k in (0, 1))
             for _, values in sorted(clusters.items())]
    if not pairs:
        raise ValueError("empty evaluation groups")
    rng = random.Random(seed)
    n = len(pairs)
    draws = [[], []]
    for _ in range(replicates):
        selections = [rng.randrange(n) for _ in range(n)]
        for k in (0, 1):
            draws[k].append(sum(pairs[j][k] for j in selections) / n)
    return {
        "groups": n,
        "accuracy_gain": sum(p[0] for p in pairs) / n,
        "accuracy_gain_bonferroni_lcb": percentile(draws[0], alpha),
        "brier_delta": sum(p[1] for p in pairs) / n,
        "brier_delta_bonferroni_ucb": percentile(draws[1], 1 - alpha),
    }


def validate_resource_reports(reports, trial):
    if reports is None:
        return False
    if not isinstance(reports, list) or len(reports) != len(SCALES):
        raise ValueError("64/256/1024/4096 paired scale receipts required")
    observed = set()
    all_coverage = True
    for receipt in reports:
        if (receipt.get("schema") != "hepta.neuron-research-paired-resource-gate.v1" or
                receipt.get("candidate_model") != trial["model"] or
                receipt.get("candidate_revision") != trial["revision"] or
                receipt.get("production_promotion_permitted") is not False or
                receipt.get("independent_ndu_signature_verified") is not False or
                receipt.get("production_microbatch_qualified") is not False or
                receipt.get("production_recovery_qualified") is not False):
            raise ValueError("unbound or falsely promoted resource receipt")
        scale = receipt.get("scale", {})
        n = scale.get("logical_cells")
        if type(n) is not int or n not in SCALES or n in observed:
            raise ValueError("duplicate, missing or unregistered scale size")
        observed.add(n)
        if type(receipt.get("research_resource_gate_passed")) is not bool:
            raise ValueError("missing independent research resource verdict")
        for metric in ("candidate_max_stage_p99_ms", "candidate_rss_bytes",
                       "candidate_throughput_rps"):
            value = receipt.get("metrics", {}).get(metric)
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ValueError("missing measured resource cost")
        active = scale.get("active_heads")
        covered = scale.get("distinct_ticked_cells")
        if (type(active) is not int or type(covered) is not int or
                not 1 <= covered <= active <= n):
            raise ValueError("missing physically ticked active Cell coverage")
        all_coverage = (all_coverage and
                        scale.get("measured_active_cell_coverage") is True and
                        covered == active)
    if observed != set(SCALES):
        raise ValueError("full 64/256/1024/4096 scale matrix missing")
    return all_coverage and all(r["research_resource_gate_passed"] for r in reports)


def review(dataset, trial, journal_bytes, nochange, *,
           resources=None, min_future_groups=30, replicates=2000, seed=20261011):
    if type(replicates) is not int or replicates < 1000:
        raise ValueError("bootstraps require at least 1000 draws")
    if type(min_future_groups) is not int or min_future_groups < 2:
        raise ValueError("future groups must be bounded")
    indexed, audit, owner = verify_and_index(
        dataset, trial, journal_bytes, nochange)
    pairing = {}
    for index, window in enumerate(WINDOWS):
        items = [item for item in indexed.values()
                 if item["dataset"]["future_window"] == window]
        pairing[window] = {
            control: window_bootstrap(items, control=control,
                                      seed=seed + index * 2 + other,
                                      replicates=replicates)
            for other, control in enumerate(("no_change", "frozen"))
        }
    loss_limit = trial.get("precommitted_max_per_cell_retention_brier_regression")
    retention = trial.get("held_out_test_retention_before", {})
    after = trial.get("held_out_test_retention_after", {})
    if (type(loss_limit) not in (float, int) or not math.isfinite(loss_limit) or
            loss_limit < 0 or not retention or set(retention) != set(after)):
        raise ValueError("missing frozen historical retention baseline")
    regressions = {}
    for cell in retention:
        before = retention[cell].get("multiclass_brier")
        later = after[cell].get("multiclass_brier")
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in (before, later)):
            raise ValueError("invalid historical retention evidence")
        regressions[cell] = later - before
    retention_ok = (not trial.get("per_cell_retention_regressions") and
                    trial.get("no_retention_regression_above_precommitted_tolerance") is True and
                    all(v <= loss_limit for v in regressions.values()))
    all_future = all(
        item["groups"] >= min_future_groups and
        item["accuracy_gain_bonferroni_lcb"] > 0 and
        item["brier_delta_bonferroni_ucb"] < 0
        for part in pairing.values() for item in part.values())
    resource_ok = validate_resource_reports(resources, trial)
    predictive_pass = all_future and retention_ok
    return {
        "schema": SCHEMA,
        "status": "offline_three_way_test_then_learn_diagnostic_not_independent_ndu",
        "production_promotion_permitted": False,
        "independent_evaluator_signature_verified": False,
        "signed_nochange_owner_receipt_verified": False,
        "genuine_future_outcome_authentication_verified": False,
        "production_worker_4096_cell_evidence_verified": False,
        "quality_three_way_precheck_passed": predictive_pass,
        "four_scale_research_resource_precheck_passed": resource_ok,
        "joint_offline_diagnostic_passed": predictive_pass and resource_ok,
        "dataset_digest": audit["dataset_digest"],
        "trial_digest": sha256_record(trial),
        "no_change_prediction_digest": sha256_record(nochange),
        "pre_label_prediction_journal_sha256": trial["pre_label_prediction_journal_sha256"],
        "no_change_model_identity_unverified": {
            "revision": owner[0], "weights_digest": owner[1], "generation": owner[2]},
        "future_grouped_paired": pairing,
        "historical_per_cell_brier_regression": regressions,
        "retention_cap": loss_limit,
        "limitations": [
            "No-change JSON/model identity and offline labels are NOT authenticated by this script",
            "A journal SHA and fsync claim are not a signature or live receipt",
            "Resource pairs measure research Python, not native Rust Worker physical dispatch",
            "A positive predictive gain cannot replace causal external NDU/future outcome receipts",
            "Selector, Executor, Artifact CAS, generation-fenced final-use and unclean crash recovery remain unverified",
        ],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--trial", required=True)
    p.add_argument("--prelabel-journal", required=True)
    p.add_argument("--no-change", required=True)
    p.add_argument("--resources", help="JSON array of four paired research scale gates")
    p.add_argument("--output", required=True)
    p.add_argument("--min-future-groups", type=int, default=30)
    p.add_argument("--bootstrap-replicates", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20261011)
    a = p.parse_args()
    dataset = read_jsonl(a.dataset)
    trial = json.loads(Path(a.trial).read_text(encoding="utf-8"))
    nochange = read_jsonl(a.no_change)
    resource = json.loads(Path(a.resources).read_text(encoding="utf-8")) if a.resources else None
    result = review(dataset, trial, Path(a.prelabel_journal).read_bytes(),
                    nochange, resources=resource, min_future_groups=a.min_future_groups,
                    replicates=a.bootstrap_replicates, seed=a.seed)
    write_json(a.output, result)


if __name__ == "__main__":
    main()
