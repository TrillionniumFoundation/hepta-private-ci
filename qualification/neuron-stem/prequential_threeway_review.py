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
from qualified_eval import audit_dataset, percentile, read_jsonl, strict_json_loads

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
        lines = raw.decode("utf-8").splitlines()
        if not lines or any(not line.strip() for line in lines):
            raise ValueError("blank or missing prediction journal row")
        records = [strict_json_loads(line) for line in lines]
        if any(type(record) is not dict for record in records):
            raise ValueError("prediction journal requires object records")
        return records
    except (UnicodeError, ValueError, TypeError) as exc:
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
    last_committed_head = {}
    any_head_update = False
    updates_per_event = trial.get("update_steps_per_future_event")
    if type(updates_per_event) is not int or updates_per_event < 0:
        raise ValueError("missing precommitted per-event optimizer update count")
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
        if (type(record.get("local_update_steps_after_prediction")) is not int or
                record["local_update_steps_after_prediction"] != updates_per_event):
            raise ValueError("local Cell update steps disagree with frozen trial protocol")
        if updates_per_event == 0 and record["postupdate_head_digest"] != prec["head_digest"]:
            raise ValueError("no-update Cell must not claim changing Head weights")
        classes = len(row["options"])
        valid_probs(record["trained_probabilities"], classes)
        valid_probs(record["frozen_same_initialization_probabilities"], classes)
        key = (row["scope_id"], row["cell_id"])
        initial_key = str(key)
        if initial_key not in initial:
            raise ValueError("missing frozen same-initialization Cell Head")
        require_sha(initial[initial_key])
        frozen_digest = prec.get("frozen_control_head_digest")
        require_sha(frozen_digest)
        if (frozen_digest != initial[initial_key] or
                record.get("frozen_control_head_digest") != frozen_digest or
                prec.get("frozen_control_probabilities") !=
                record.get("frozen_same_initialization_probabilities")):
            raise ValueError("frozen Head weights/probabilities changed or were not precommitted")
        if key in last_committed_head and prec["head_digest"] != last_committed_head[key]:
            raise ValueError("discontinuous Cell Head update digest lineage")
        if key not in earliest_by_cell:
            if (prec["head_digest"] != initial[initial_key] or
                    any(abs(a - b) > 1e-6
                        for a, b in zip(record["trained_probabilities"],
                                        record["frozen_same_initialization_probabilities"]))):
                raise ValueError("initial learned/frozen Head mismatch before first update")
            earliest_by_cell.add(key)
        any_head_update |= record["postupdate_head_digest"] != prec["head_digest"]
        last_committed_head[key] = record["postupdate_head_digest"]
        indexed[row["case_id"]] = {
            "dataset": row,
            "trained": record["trained_probabilities"],
            "frozen": record["frozen_same_initialization_probabilities"],
        }
    if trial.get("pre_label_prediction_journal_event_count") != len(futures):
        raise ValueError("wrong committed prediction count")
    final_heads = trial.get("final_head_digests")
    # The original prequential trainer also registers Cells with only historic
    # examples. Such Cells never receive a future event and retain their
    # pre-future Head. Requiring only future-ticked keys would falsely reject
    # valid datasets with dormant Cells.
    expected_final = dict(initial)
    expected_final.update({str(key): digest
                           for key, digest in last_committed_head.items()})
    if type(final_heads) is not dict or final_heads != expected_final:
        raise ValueError("final Cell Head artifact digests do not match replayed update chain")
    if trial.get("frozen_final_head_digests") != initial:
        raise ValueError("frozen final Head tensor digests changed during future learning")
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
    return indexed, audit, nochange_identity, bool(updates_per_event and any_head_update)


def measure(probs, correct_index):
    winner = max(range(len(probs)), key=lambda i: probs[i])
    return (float(winner == correct_index),
            sum((p - float(i == correct_index)) ** 2
                for i, p in enumerate(probs)) / len(probs))


def future_calibration_metrics(rows, arm, bins=15):
    """Descriptive ECE/Brier on offline future labels; NEVER an NDU receipt."""
    if arm not in ("trained", "frozen", "no_change") or not rows:
        raise ValueError("unknown or empty precommitted future calibration arm")
    if type(bins) is not int or bins != 15:
        raise ValueError("only the fixed 15-bin ECE is registered")
    grouped = [[] for _ in range(bins)]
    accuracy, brier = 0.0, 0.0
    for record in rows:
        y = record["dataset"]["label"]
        probs = record[arm]
        valid_probs(probs, len(record["dataset"]["options"]))
        won = max(range(len(probs)), key=probs.__getitem__)
        correct = float(won == y)
        confidence = probs[won]
        accuracy += correct
        brier += sum((p - float(i == y)) ** 2
                     for i, p in enumerate(probs)) / len(probs)
        grouped[min(bins - 1, int(confidence * bins))].append(
            (confidence, correct))
    n = len(rows)
    ece = sum(len(items) / n *
              abs(sum(item[0] for item in items) / len(items) -
                  sum(item[1] for item in items) / len(items))
              for items in grouped if items)
    return {
        "events": n,
        "accuracy": accuracy / n,
        "normalized_multiclass_brier": brier / n,
        "ece_15": ece,
        "outcomes": "offline_dataset_labels_unattested_not_independent_ndu",
    }


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


def offline_threeway_ood_diagnostic(dataset, trial, nochange_identity, receipts):
    """Paired ID-calibration/OOD diagnostic; NOT authenticated NDU or a gate.

    This accepts only *externally provided* per-arm model probabilities.
    Training code must not create its own no-change control. The OOD threshold
    is fixed from historical calibration input before OOD labels are examined.
    Even complete local input coverage is neither a producer signature nor
    authority to deploy a Cell.
    """
    if type(receipts) is not list or not receipts:
        raise ValueError("missing three-way offline OOD evidence")
    relevant = {row["case_id"]: row for row in dataset
                if row["task_id"] == trial["task_id"] and
                row["split"] in ("calibration", "ood")}
    calibration = [row for row in relevant.values() if row["split"] == "calibration"]
    ood = [row for row in relevant.values() if row["split"] == "ood"]
    future = [row for row in dataset
              if row["task_id"] == trial["task_id"] and row["split"] == "future"]
    if (not calibration or not ood or not future or
            min(event_time(row) for row in ood) <= max(event_time(row) for row in future)):
        raise ValueError("OOD must be sampled strictly after the entire future learning window")
    arms = ("no_change", "frozen", "trained")
    expected = {(row["case_id"], arm) for row in relevant.values() for arm in arms}
    if len(receipts) != len(expected):
        raise ValueError("OOD requires full three-arm calibration and OOD coverage")
    nochange_rev, nochange_weights, nochange_gen = nochange_identity
    # A reused Head digest is not sufficient identity across Worker generations
    # or Encoder revisions. Require the frozen trial's exact model-only lineage
    # before interpreting even a descriptive OOD comparison.
    generation = trial.get("generation")
    if type(generation) is not int or generation <= 0:
        raise ValueError("offline OOD trial lacks pinned Stem/Cell generation")
    feature_manifest_digest = trial.get("feature_manifest_digest")
    require_sha(feature_manifest_digest)
    # The original model-only sidecar is created and fsynced before the
    # no-change arm is merged. Its exact byte SHA must remain bound to this
    # trial; per-row identity matching cannot detect substituted logits alone.
    sidecar_digest = trial.get("offline_ood_model_receipts_sha256")
    require_sha(sidecar_digest)
    observed = {}
    verified_source_rows = {}
    forbidden = {"label", "outcome", "external_ndu_utility", "total_cost",
                 "producer_signature_verified", "independent_evaluator_signature_verified"}
    for receipt in receipts:
        if type(receipt) is not dict or any(field in receipt for field in forbidden):
            raise ValueError("OOD prediction cannot smuggle outcome or verification authority")
        case_id, arm = receipt.get("case_id"), receipt.get("arm")
        key = (case_id, arm)
        if key not in expected or key in observed:
            raise ValueError("unknown, duplicate or missing paired OOD arm")
        row = relevant[case_id]
        if (receipt.get("production_promotion_permitted") is not False or
                receipt.get("status") != "Succeeded" or
                receipt.get("scope_id") != row["scope_id"] or
                receipt.get("cell_id") != row["cell_id"] or
                receipt.get("split") != row["split"] or
                receipt.get("event_time") != row["event_time"] or
                receipt.get("input_digest") != sha256_record(
                    [row["state"], row["question"], row["options"]])):
            raise ValueError("OOD source/Cell/option ordering is not bound")
        valid_probs(receipt.get("probabilities"), len(row["options"]))
        if arm == "no_change":
            identity_ok = (receipt.get("model_revision") == nochange_rev and
                           receipt.get("weights_digest") == nochange_weights and
                           receipt.get("generation") == nochange_gen and
                           receipt.get("model_id") == "no-change")
        else:
            cell_key = str((row["scope_id"], row["cell_id"]))
            declared = (trial["initial_head_digests"] if
                        arm == "frozen" or row["split"] == "calibration"
                        else trial["final_head_digests"])
            identity_ok = (receipt.get("model_revision") == trial["revision"] and
                           receipt.get("weights_digest") == declared.get(cell_key) and
                           receipt.get("model_id") == trial["model"] and
                           receipt.get("generation") == generation and
                           receipt.get("feature_manifest_digest") ==
                           feature_manifest_digest)
        if not identity_ok:
            raise ValueError("OOD frozen/learned/no-change weight or generation lineage drifted")
        observed[key] = receipt["probabilities"]
        verified_source_rows[key] = receipt
    if set(observed) != expected:
        raise ValueError("missing exact paired calibration/OOD predictions")
    # Canonicalize the 2-arm model-only projection of the 3-arm review in the
    # EXACT producer order: historical calibration, then post-future OOD;
    # chronological event/case order; Frozen before learned. Do not include
    # externally supplied production no-change records in the Stem sidecar.
    model_rows = []
    for cohort in (calibration, ood):
        for source in sorted(cohort, key=lambda item: (event_time(item), item["case_id"])):
            for arm in ("frozen", "trained"):
                model_rows.append(verified_source_rows[(source["case_id"], arm)])
    sidecar_bytes = "".join(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                   separators=(",", ":")) + "\n"
        for value in model_rows
    ).encode("utf-8")
    if hashlib.sha256(sidecar_bytes).hexdigest() != sidecar_digest:
        raise ValueError("frozen/learned OOD model sidecar byte digest mismatch")
    for row in calibration:
        if any(abs(a - b) > 1e-6 for a, b in zip(
                observed[(row["case_id"], "trained")],
                observed[(row["case_id"], "frozen")])):
            raise ValueError("calibration learned and frozen Heads must share initial state")

    measures = {}
    for arm in arms:
        calibration_conf = [max(observed[(row["case_id"], arm)])
                            for row in calibration]
        threshold = percentile(calibration_conf, .05)
        false_accepts = sum(
            max(observed[(row["case_id"], arm)]) >= threshold for row in ood)
        accepted_calibration = sum(conf >= threshold for conf in calibration_conf)
        measures[arm] = {
            "calibration_cases": len(calibration),
            "calibration_groups": len({(r["scope_id"], r["group_id"])
                                        for r in calibration}),
            "ood_cases": len(ood),
            "ood_groups": len({(r["scope_id"], r["group_id"]) for r in ood}),
            "threshold_from_historical_calibration": threshold,
            "historical_calibration_accept_rate": accepted_calibration / len(calibration),
            "ood_false_accept_rate": false_accepts / len(ood),
            "basis": "unsigned_offline_predictions_and_dataset_labels_not_independent_NDU",
        }
    return {
        "threeway_exact_offline_coverage": True,
        "frozen_feature_manifest_digest": feature_manifest_digest,
        "frozen_stem_cell_generation": generation,
        "production_promotion_permitted": False,
        "independent_prediction_signature_verified": False,
        "ood_after_future_window_verified": True,
        "results": measures,
        "trained_ood_far_delta_vs_frozen": (
            measures["trained"]["ood_false_accept_rate"] -
            measures["frozen"]["ood_false_accept_rate"]),
        "trained_ood_far_delta_vs_no_change": (
            measures["trained"]["ood_false_accept_rate"] -
            measures["no_change"]["ood_false_accept_rate"]),
        "negative_transfer_ood_far_vs_frozen": (
            measures["trained"]["ood_false_accept_rate"] >
            measures["frozen"]["ood_false_accept_rate"]),
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


def verify_feature_cache_budget(trial):
    """Check a self-reported retained tensor budget, never process RSS.

    Older shadow trials legitimately lack this optional field and are marked
    unverified; a partially populated or impossible newer receipt is denied.
    """
    keys = ("max_feature_cache_bytes", "feature_cache_peak_resident_bytes",
            "feature_cache_resident_bytes", "feature_cache_retained_cases",
            "feature_cache_evictions", "feature_cache_hits",
            "feature_cache_misses", "feature_cache_is_not_process_rss")
    if not any(key in trial for key in keys):
        return {
            "receipt_present": False,
            "budget_consistency_verified": False,
            "independently_attested": False,
            "production_rss_qualified": False,
        }
    if any(key not in trial for key in keys):
        raise ValueError("partial learned Cell Feature cache resource receipt")
    ceiling, peak, resident, retained, evictions, hits, misses = (
        trial[key] for key in keys[:-1])
    if (any(type(x) is not int for x in (
            ceiling, peak, resident, retained, evictions, hits, misses)) or
            not 4096 <= ceiling <= 512 * 1024 * 1024 or
            not 0 <= resident <= peak <= ceiling or
            retained < 0 or evictions < 0 or hits < 0 or misses <= 0 or
            (retained > 0 and resident == 0) or
            (retained == 0 and resident != 0) or
            trial["feature_cache_is_not_process_rss"] is not True):
        raise ValueError("invalid or unbounded learned Cell Feature cache receipt")
    return {
        "receipt_present": True,
        "budget_consistency_verified": True,
        "independently_attested": False,
        "production_rss_qualified": False,
        "max_retained_tensor_bytes": ceiling,
        "peak_retained_tensor_bytes": peak,
        "cache_evictions": evictions,
        "cache_hits": hits,
        "cache_misses": misses,
    }


def review(dataset, trial, journal_bytes, nochange, *,
           resources=None, ood_receipts=None, min_future_groups=30,
           replicates=2000, seed=20261011):
    if type(replicates) is not int or replicates < 1000:
        raise ValueError("bootstraps require at least 1000 draws")
    if type(min_future_groups) is not int or min_future_groups < 2:
        raise ValueError("future groups must be bounded")
    indexed, audit, owner, head_learning_evidence = verify_and_index(
        dataset, trial, journal_bytes, nochange)
    pairing = {}
    calibration = {}
    for index, window in enumerate(WINDOWS):
        items = [item for item in indexed.values()
                 if item["dataset"]["future_window"] == window]
        pairing[window] = {
            control: window_bootstrap(items, control=control,
                                      seed=seed + index * 2 + other,
                                      replicates=replicates)
            for other, control in enumerate(("no_change", "frozen"))
        }
        calibration[window] = {
            arm: future_calibration_metrics(items, arm)
            for arm in ("no_change", "frozen", "trained")
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
    feature_cache_evidence = verify_feature_cache_budget(trial)
    offline_ood = (offline_threeway_ood_diagnostic(
        dataset, trial, owner, ood_receipts)
        if ood_receipts is not None else None)
    predictive_pass = all_future and retention_ok and head_learning_evidence
    return {
        "schema": SCHEMA,
        "status": "offline_three_way_test_then_learn_diagnostic_not_independent_ndu",
        "production_promotion_permitted": False,
        "independent_evaluator_signature_verified": False,
        "signed_nochange_owner_receipt_verified": False,
        "genuine_future_outcome_authentication_verified": False,
        "production_worker_4096_cell_evidence_verified": False,
        "quality_three_way_precheck_passed": predictive_pass,
        "sealed_cell_update_chain_consistent": True,
        "frozen_control_head_weights_sealed_and_unchanged": True,
        "observed_actual_head_parameter_change_in_offline_trace": head_learning_evidence,
        "four_scale_research_resource_precheck_passed": resource_ok,
        "offline_feature_cache_budget_diagnostic": feature_cache_evidence,
        "joint_offline_diagnostic_passed": predictive_pass and resource_ok,
        "dataset_digest": audit["dataset_digest"],
        "trial_digest": sha256_record(trial),
        "no_change_prediction_digest": sha256_record(nochange),
        "pre_label_prediction_journal_sha256": trial["pre_label_prediction_journal_sha256"],
        "no_change_model_identity_unverified": {
            "revision": owner[0], "weights_digest": owner[1], "generation": owner[2]},
        "future_grouped_paired": pairing,
        "future_window_calibration_descriptive": calibration,
        "ece_15_calculated_for_all_three_controls": True,
        "ood_threeway_model_evidence_present": False,
        "offline_ood_threeway_diagnostic": offline_ood,
        "offline_ood_threeway_coverage_present": offline_ood is not None,
        "full_quality_and_ood_gate_passed": False,
        "historical_per_cell_brier_regression": regressions,
        "retention_cap": loss_limit,
        "limitations": [
            "No-change JSON/model identity and offline labels are NOT authenticated by this script",
            "A journal SHA and fsync claim are not a signature or live receipt",
            "Resource pairs measure research Python, not native Rust Worker physical dispatch",
            "A positive predictive gain cannot replace causal external NDU/future outcome receipts",
            ("Paired OOD model predictions are only unsigned local research evidence, not a signed OOD/NDU gate"
             if offline_ood is not None else
             "Paired OOD model predictions are absent; ECE on offline future labels does not satisfy OOD gate"),
            "Selector, Executor, Artifact CAS, generation-fenced final-use and unclean crash recovery remain unverified",
        ],
    }


def write_frozen_report(path, report):
    """No replay may silently overwrite previously reviewed outcomes."""
    # Reject nonfinite/incomplete reports BEFORE creating an immutable path.
    serialized = json.dumps(report, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False) + "\n"
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(serialized)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--trial", required=True)
    p.add_argument("--prelabel-journal", required=True)
    p.add_argument("--no-change", required=True)
    p.add_argument("--resources", help="JSON array of four paired research scale gates")
    p.add_argument("--ood-receipts", help="External unsigned three-way calibration/OOD JSONL")
    p.add_argument("--output", required=True)
    p.add_argument("--min-future-groups", type=int, default=30)
    p.add_argument("--bootstrap-replicates", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20261011)
    a = p.parse_args()
    dataset = read_jsonl(a.dataset)
    trial = strict_json_loads(Path(a.trial).read_text(encoding="utf-8"))
    nochange = read_jsonl(a.no_change)
    resource = strict_json_loads(Path(a.resources).read_text(encoding="utf-8")) if a.resources else None
    ood = read_jsonl(a.ood_receipts) if a.ood_receipts else None
    result = review(dataset, trial, Path(a.prelabel_journal).read_bytes(),
                    nochange, resources=resource, ood_receipts=ood,
                    min_future_groups=a.min_future_groups,
                    replicates=a.bootstrap_replicates, seed=a.seed)
    write_frozen_report(a.output, result)


if __name__ == "__main__":
    main()
