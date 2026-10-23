"""Precommitted real-Encoder evolution experiment on unused historical stories.

The primary comparison matches two resident slots, parameter-example updates,
SGD state and selected Head calls. Explicit caller partitions do not demonstrate
an automatic split trigger. No source-ledger authentication or deployment grant.
"""

import argparse
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np
import torch

from cell_evolution_snapshot import (EvolutionBudgetV1, EvolutionError, OfflineEvolutionOwnerV1,
    WithdrawalViewV1, bootstrap_snapshot, group_digest, load_snapshot, retire_snapshot, rollback_snapshot)
from cell_evolution_training import (EvolutionTrainingConfigV1, continue_snapshot,
                                     merge_snapshot, split_snapshot)
from cell_head_training import HeadCohortV1, HeadTrainingConfigV1, train_cell_head
from cell_router_training import RouterCellV1, RouterTrainingConfigV1, train_cell_router
from feature_bundle import FeatureBundleV1
from native_latent import LightCellHead
from prepare_news_cohorts import (ARCHIVE_SHA256, _read_archive, canonical, load_cohorts,
                                  normalized_title, publisher_is_ood, sha)
from real_encoder import CANDIDATES, FrozenRealEncoder
from real_model_bakeoff import code_identity, model_tensor_digest, rss_observation
from real_router_probe import paired_interval, probability_metrics

SEEDS = (7, 17, 29)
HOLDOUTS = ("future_1", "future_2", "ood")
ROLES = {
    "parent_a": ("2014-03", 96, False), "parent_b": ("2014-03", 96, False),
    "parent_router_train": ("2014-03", 64, False),
    "parent_head_calibration": ("2014-04", 64, False),
    "parent_router_calibration": ("2014-04", 64, False),
    "replay_a": ("2014-05", 96, False), "replay_b": ("2014-05", 96, False),
    "router_train": ("2014-05", 64, False),
    "head_calibration": ("2014-06", 64, False), "router_calibration": ("2014-06", 64, False),
    "merge_calibration": ("2014-06", 64, False),
    "future_1": ("2014-07", 128, False), "future_2": ("2014-08", 96, False),
    "ood": ("2014-07", 48, True),
}


def select_unused_rows(source, excluded):
    """First story occurrence, canonical-title dedup, then fixed hash assignment."""
    old = [row for values in excluded.values() for row in values]
    old_groups = {row["source_group_id"] for row in old}
    old_titles = {normalized_title(row["text"]) for row in old}
    old_ids = {row["source_id"] for row in old}
    stories = {}
    for row in source:
        key = row["source_group_id"]
        if key not in stories or (row["timestamp_ms"], row["source_id"]) < (
                stories[key]["timestamp_ms"], stories[key]["source_id"]):
            stories[key] = row
    titles = {}
    for row in sorted(stories.values(), key=lambda r: (r["timestamp_ms"], r["source_id"])):
        titles.setdefault(normalized_title(row["text"]), row)
    buckets = defaultdict(list)
    for title, row in titles.items():
        if row["source_group_id"] in old_groups or title in old_titles or row["source_id"] in old_ids:
            continue
        month = datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m")
        buckets[(month, publisher_is_ood(row["publisher"]), row["label"])].append(row)
    for values in buckets.values():
        values.sort(key=lambda r: sha(("hepta-evolution-v1:" + r["source_id"]).encode()))
    used, selected = set(), {}
    for name, (month, count, ood) in ROLES.items():
        rows = []
        for label in range(4):
            eligible = [r for r in buckets[(month, ood, label)] if r["source_group_id"] not in used]
            if len(eligible) < count // 4:
                raise ValueError(f"precommitted cohort {name} lacks independent stories for class {label}")
            rows.extend(eligible[:count // 4])
        used.update(r["source_group_id"] for r in rows)
        selected[name] = sorted(rows, key=lambda r: sha(("order:evolution-v1:" + r["source_id"]).encode()))
    all_rows = [r for values in selected.values() for r in values]
    if (len(used) != len(all_rows) or used & old_groups
            or len({normalized_title(r["text"]) for r in all_rows}) != len(all_rows)):
        raise ValueError("new cohort group/title isolation failed")
    return selected


def combine(cohorts):
    values = list(cohorts)
    identity = values[0].bundle.identity
    for cohort in values:
        cohort.bundle.require_identity(identity)
    features = torch.cat([c.bundle.read_global() for c in values])
    missing = torch.ones((len(features), 5), dtype=torch.bool)
    missing[:, 0] = False
    bundle = FeatureBundleV1.from_tensors(global_features=features, identity=identity, missing_mask=missing,
        source_record_digests=tuple(s for c in values for s in c.bundle.source_record_digests))
    return HeadCohortV1(bundle, tuple(label for c in values for label in c.labels),
                        tuple(group for c in values for group in c.source_group_ids))


def _write(path, value):
    data = canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(data)
    return sha(data)


def _measure(function, *args, **kwargs):
    """Observe real Head forwards, including initial scoring and all calibration."""
    counts = {"head_example_calls": 0, "head_module_invocations": 0}
    original = LightCellHead.forward
    def forward(module, features, state):
        counts["head_example_calls"] += len(features)
        counts["head_module_invocations"] += 1
        return original(module, features, state)
    with patch.object(LightCellHead, "forward", new=forward):
        result = function(*args, **kwargs)
    return result, counts


def _plan(target, inventory_sha256, old_manifest, old_rows, batch_size, threads):
    # These numerical caps follow the fixed width=384/rank=4/state=8/four-class ABI.
    budget = EvolutionBudgetV1(resident_tensor_bytes=86368, gradient_bytes=24776,
        head_example_calls=21248, parameter_example_updates=175379200, router_example_steps=12800)
    head = HeadTrainingConfigV1(task_count=4, mode="gated", steps=200, learning_rate=0.2)
    router = RouterTrainingConfigV1(steps=200, learning_rate=0.1, top_k=1, budget_units=1)
    evolution = EvolutionTrainingConfigV1(steps=100, learning_rate=0.1, distillation_weight=0.5)
    old = [r for rows in old_rows.values() for r in rows]
    if len(old) != 768 or len({r["source_group_id"] for r in old}) != 768:
        raise ValueError("this fixed plan requires the original 768 independent exclusion groups")
    plan = {"schema": "hepta.real-cell-evolution-plan.v1", "candidate": "granite97m",
        "plan_revision": 2,
        "availability_amendment": "before Encoder loading/scoring: August ordinary medical has 26 new stories; August OOD only 6; July OOD 14",
        "ood_sample_limit": "48 publisher-held-out July stories; limited descriptive precision",
        "checkpoint_revision": CANDIDATES["granite97m"]["revision"],
        "checkpoint_inventory_sha256": inventory_sha256, "source_archive_sha256": ARCHIVE_SHA256,
        "excluded_cohort_manifest_sha256": sha(old_manifest),
        "excluded_source_groups": sorted(r["source_group_id"] for r in old),
        "excluded_source_ids": sorted(r["source_id"] for r in old),
        "excluded_canonical_title_sha256": sorted(sha(normalized_title(r["text"]).encode()) for r in old),
        "roles_in_assignment_order": [{"name": name, "month": month, "rows": count, "publisher_ood": ood}
                                      for name, (month, count, ood) in ROLES.items()],
        "sampling": "first story occurrence; NFKC title dedup; balanced classes; hepta-evolution-v1 source-id hash",
        "partition_trigger": "explicit fixed hash partitions; no automatic quality-selected split trigger",
        "seeds": list(SEEDS), "parent_head_config": asdict(head), "router_config": asdict(router),
        "evolution_config": asdict(evolution), "per_evolution_budget": asdict(budget),
        "split_parent": "head_a", "split_children": ["child_a", "child_b"],
        "static_mapping": {"head_a": "replay_a", "head_b": "replay_b"},
        "primary_comparison": "split minus static continuation on identical replay partitions",
        "matched": ["two active Cell slots", "resident tensor bytes", "parameter-example updates",
                    "SGD state", "Router example-steps", "Head example calls", "one selected Head per inference row"],
        "excluded_from_budget_match": ["shared Encoder", "Python/native allocator", "backend workspace",
                                      "total process peak RSS", "latency", "energy"],
        "auxiliary_baselines": ["unchanged parent", "pooled_retrain"],
        "pooled_retrain": "one Head, March+May 512 train / April+June 256 calibration / 200 steps; update budget unmatched",
        "mechanics_only": {"merge": "both split teachers; replay_a+replay_b; fresh merge_calibration",
                           "retire": "child_b", "rollback": "original persisted parent; fresh generation"},
        "holdouts_select_hyperparameters_or_winner": False, "max_tokens": 128,
        "batch_size": batch_size, "encoder_cpu_threads": threads,
        "feature_scope": "memory-evolution-granite-research-v1",
        "cross_comparison_with_prior_EG2_run_valid": False,
        "claim": "single-source historical classification mechanism; foundation pretraining exposure unknown",
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False,
        "code_file_sha256": code_identity()}
    return plan, _write(target / "plan.json", plan), head, router, evolution, budget


def _encode(owner, rows, batch_size, target):
    cohorts, receipts, arrays = {}, [], {}
    before = model_tensor_digest(owner._model)
    for name, records in rows.items():
        pieces = []
        for offset in range(0, len(records), batch_size):
            batch = records[offset:offset + batch_size]
            bundle = owner.encode_text([r["text"] for r in batch], source_records=batch)
            pieces.append(HeadCohortV1(bundle, tuple(r["label"] for r in batch),
                                      tuple(r["source_group_id"] for r in batch)))
            receipts.append({"role": name, "offset": offset, **owner.last_receipt})
        cohorts[name] = combine(pieces)
        arrays[name] = cohorts[name].bundle.read_global().numpy()
        print(json.dumps({"encoded": name, "rows": len(records)}), flush=True)
    if model_tensor_digest(owner._model) != before:
        raise ValueError("shared frozen Encoder changed")
    np.savez_compressed(target / "features.npz", **arrays)
    feature_manifest = {"schema": "hepta.real-evolution-feature-cache.v1",
        "features_file_sha256": sha((target / "features.npz").read_bytes()),
        "feature_identity": asdict(owner.identity), "encoder_tensor_sha256": before,
        "cohorts": {name: c.bundle.manifest() for name, c in cohorts.items()},
        "encoder_forward_receipts": receipts, "encoder": owner.accounting,
        "single_encoding_reused_by_all_heads_arms_and_seeds": True}
    return cohorts, feature_manifest, _write(target / "feature_manifest.json", feature_manifest)


def _groups(train, calibration, holdouts):
    return {"train": train.source_group_ids, "calibration": calibration.source_group_ids,
            **{name: c.source_group_ids for name, c in holdouts.items()}}


def _evaluation(snapshot, cohorts, provider, seed, arm, ledger, phase="evaluation"):
    scores, losses, correct, probabilities = {}, {}, {}, {}
    calls = router_forwards = 0
    for name, cohort in cohorts.items():
        start = time.perf_counter()
        output, observed = _measure(snapshot.predict_task, cohort.bundle, provider)
        elapsed = (time.perf_counter() - start) * 1000
        metric, losses[name], correct[name] = probability_metrics(output["task_probabilities"], cohort.labels)
        scores[name] = {**metric, "observed_inference_ms": elapsed}
        probabilities[name] = output["task_probabilities"]
        calls += output["head_example_calls"]
        router_forwards += output["router_forward_calls"]
        if output["head_example_calls"] != observed["head_example_calls"]:
            raise ValueError("prediction ledger disagrees with observed actual Head forwards")
        if any(len(r["actual_calls"]) != 1 or r["actual_calls"] != r["selected"]
               or r["actual_cost_units"] != 1 for r in output["routes"]):
            raise ValueError("inference failed matched one-Head call budget")
        ledger.append({"seed": seed, "arm": arm, "phase": phase, "split": name,
            "observed_forward_counts": observed,
            "source_group_ids": list(cohort.source_group_ids), "labels": list(cohort.labels),
            "task_probabilities": output["task_probabilities"].tolist(),
            **{key: value for key, value in output.items() if not isinstance(value, torch.Tensor)}})
    return {"metrics": scores, "head_example_calls": calls, "router_forward_calls": router_forwards}, losses, correct, probabilities


def _reload_check(snapshot, cohort, provider, seed, arm, ledger, expected):
    loaded = load_snapshot(snapshot.directory, expected_manifest_sha256=snapshot.manifest_sha256,
                           budget=snapshot.budget, withdrawal_provider=provider)
    report, _, _, probabilities = _evaluation(loaded, {"future_1": cohort}, provider,
                                              seed, arm, ledger, phase="reload_verification")
    if not torch.equal(probabilities["future_1"], expected):
        raise ValueError("actual snapshot reload changed predictions")
    return {**report, "exact_predictions": True, "retained_manifest_sha256": snapshot.manifest_sha256}


def _mechanics(parent, split, static, cohorts, holdouts, directory, budget, provider, config, seed, ledger, parent_p):
    merged, observed_merge = _measure(merge_snapshot, split, "merged", combine([cohorts["replay_a"], cohorts["replay_b"]]),
        cohorts["merge_calibration"], holdouts, directory / "merged", budget, provider, training_config=config)
    if observed_merge["head_example_calls"] != merged.report["operation_receipt"]["actual_usage"]["head_example_calls"]:
        raise ValueError("merge receipt disagrees with actual teacher/student forwards")
    retired = retire_snapshot(split, "child_b", directory / "retired", budget, provider)
    restored = rollback_snapshot(merged, parent, directory / "rollback", budget, provider)
    owner = OfflineEvolutionOwnerV1(split, provider)
    owner.commit(merged, expected_parent_manifest_sha256=split.manifest_sha256)
    owner.commit(restored, expected_parent_manifest_sha256=merged.manifest_sha256)
    results = {}
    for arm, snapshot in (("merged", merged), ("retired", retired), ("rollback", owner.current)):
        report, _, _, values = _evaluation(snapshot, {"future_1": holdouts["future_1"]}, provider,
                                            seed, arm, ledger, phase="mechanism_check")
        report["reload"] = _reload_check(snapshot, holdouts["future_1"], provider, seed, arm,
                                          ledger, values["future_1"])
        report["snapshot_manifest_sha256"] = snapshot.manifest_sha256
        report["graph_generation"] = snapshot.generation
        report["resident_tensor_bytes"] = snapshot.report["resident_tensor_bytes"]
        if arm == "retired":
            routes = ledger[-2]["routes"]
            actual_retired = sum("child_b" in row["actual_calls"] for row in routes)
            if actual_retired or report["router_forward_calls"]:
                raise ValueError("retired Cell or dropped Router executed")
            report["retired_cell_example_calls"] = actual_retired
        if arm == "rollback" and not torch.equal(values["future_1"], parent_p):
            raise ValueError("rollback did not restore original parent outputs")
        results[arm] = report
    checks = []
    origins = {
        "retired_parent_b_train": parent.cells[1].head.report["splits"]["train"]["source_record_digests"][0],
        "parent_router_calibration": group_digest(parent.report["router"]["source_groups"]["calibration"][0]),
        "child_train": split.cells[0].head.report["splits"]["train"]["source_record_digests"][0],
        "child_router_train": split.router.report["splits"]["train"]["source_record_digests"][0],
    }
    for origin, source in origins.items():
        withdrawn = WithdrawalViewV1(parent.identity.scope_id, epoch=1, revoked_source_digests=(source,))
        revoked_provider = lambda view=withdrawn: view
        rejected = []
        snapshots = [split, static, merged, retired] + ([restored] if origin.startswith("parent") or origin.startswith("retired_parent") else [])
        with patch.object(LightCellHead, "forward", side_effect=AssertionError("withdrawn graph executed")) as spy:
            for snapshot in snapshots:
                try:
                    snapshot.predict_task(holdouts["future_1"].bundle, revoked_provider)
                except EvolutionError as error:
                    if "withdrawn" not in str(error):
                        raise
                    rejected.append(snapshot.manifest_sha256)
                else:
                    raise ValueError("withdrawn source did not invalidate the entire network")
            actual_calls = spy.call_count
        checks.append({"origin": origin, "source_digest": source, "rejected_snapshot_digests": rejected,
                       "actual_Head_module_calls": actual_calls})
        if origin == "child_train":
            clean = rollback_snapshot(split, parent, directory / "clean-parent-recovery", budget, revoked_provider)
            report, _, _, values = _evaluation(clean, {"future_1": holdouts["future_1"]}, revoked_provider,
                seed, "clean_parent_recovery", ledger, phase="withdrawal_recovery")
            if not torch.equal(values["future_1"], parent_p):
                raise ValueError("clean parent recovery changed original outputs")
            results["clean_parent_recovery"] = {**report, "graph_generation": clean.generation,
                "snapshot_manifest_sha256": clean.manifest_sha256, "original_predictions_exact": True}
    return {"operations": results, "withdrawal_checks": checks,
            "observed_merge_forward_counts": observed_merge,
            "merge_teacher_head_example_calls": merged.report["operation_receipt"]["teacher_head_example_calls"],
            "merge_operation_receipt": merged.report["operation_receipt"], "quality_advantage_claimed": False}


def run_probe(*, snapshot, inventory_sha256, cohorts, archive, output,
              operator_accepted_terms, batch_size=16, threads=4):
    if operator_accepted_terms is not True or not 1 <= batch_size <= 32 or not 1 <= threads <= 8:
        raise ValueError("bounded explicit research execution required")
    torch.set_num_threads(threads)
    torch.manual_seed(7)
    original_manifest = (Path(cohorts) / "manifest.json").read_bytes()
    _, excluded = load_cohorts(cohorts, expected_manifest_sha256=sha(original_manifest), archive=archive)
    target = Path(output)
    target.mkdir(parents=True, exist_ok=False)
    plan, plan_sha, head_config, router_config, evolution_config, budget = _plan(
        target, inventory_sha256, original_manifest, excluded, batch_size, threads)
    # The immutable plan exists before selection, Encoder loading or test scoring.
    rows = select_unused_rows(_read_archive(archive), excluded)
    cohort_sha = _write(target / "cohorts.json", rows)
    cohort_manifest = {"schema": "hepta.unused-news-evolution-cohorts.v1", "plan_sha256": plan_sha,
        "source_archive_sha256": ARCHIVE_SHA256, "cohort_file_sha256": cohort_sha,
        "excluded_manifest_sha256": sha(original_manifest), "excluded_groups": 768,
        "splits": {name: {"rows": len(values), "source_groups": [r["source_group_id"] for r in values],
            "min_timestamp_ms": min(r["timestamp_ms"] for r in values),
            "max_timestamp_ms": max(r["timestamp_ms"] for r in values)} for name, values in rows.items()},
        "source": "Gasparetti, F. (2017). News Aggregator. UCI. doi:10.24432/C5F61C; CC-BY-4.0",
        "foundation_pretraining_exposure_excluded": False, "prospective_deployment_windows": 0}
    cohort_manifest_sha = _write(target / "cohort_manifest.json", cohort_manifest)
    began, rss_before = time.perf_counter(), rss_observation()
    owner = FrozenRealEncoder(candidate="granite97m", snapshot=snapshot,
        revision=plan["checkpoint_revision"], expected_inventory_sha256=inventory_sha256,
        operator_accepted_terms=True, profile="text", max_tokens=128, scope_id=plan["feature_scope"])
    encoded, feature_manifest, feature_sha = _encode(owner, rows, batch_size, target)
    holdouts = {name: encoded[name] for name in HOLDOUTS}
    provider = lambda: WithdrawalViewV1(owner.identity.scope_id)
    ledger, reports = [], []
    pooled_train = combine([encoded[name] for name in ("parent_a", "parent_b", "parent_router_train",
                                                      "replay_a", "replay_b", "router_train")])
    pooled_cal = combine([encoded[name] for name in ("parent_head_calibration", "parent_router_calibration",
                                                    "head_calibration", "router_calibration")])
    for seed in SEEDS:
        directory = target / f"seed-{seed}"
        directory.mkdir()
        cells, common_calls = [], []
        for index, cell_id in enumerate(("head_a", "head_b")):
            replay = encoded["parent_a" if index == 0 else "parent_b"]
            head, observed = _measure(train_cell_head, replay, encoded["parent_head_calibration"], holdouts,
                                   config=replace(head_config, seed=seed + index))
            common_calls.append({"phase": cell_id, **observed})
            cells.append(RouterCellV1(cell_id, head, 1, _groups(replay, encoded["parent_head_calibration"], holdouts)))
        router, observed = _measure(train_cell_router, encoded["parent_router_train"], encoded["parent_router_calibration"],
                                   holdouts, cells, replace(router_config, seed=seed))
        common_calls.append({"phase": "parent_router", **observed})
        parent = bootstrap_snapshot(cells, router, _groups(encoded["parent_router_train"],
            encoded["parent_router_calibration"], holdouts), directory / "parent", budget, provider)
        shared = dict(calibration=encoded["head_calibration"], holdouts=holdouts,
            router_train=encoded["router_train"], router_calibration=encoded["router_calibration"],
            budget=budget, withdrawal_provider=provider, training_config=evolution_config,
            router_config=replace(router_config, seed=seed))
        split, observed_split = _measure(split_snapshot, parent, "head_a", {"child_a": encoded["replay_a"], "child_b": encoded["replay_b"]},
                               directory=directory / "split", **shared)
        static, observed_static = _measure(continue_snapshot, parent, {"head_a": encoded["replay_a"], "head_b": encoded["replay_b"]},
                                   directory=directory / "static", **shared)
        split_usage, static_usage = (s.report["operation_receipt"]["actual_usage"] for s in (split, static))
        if (split_usage != static_usage or split.report["operation_receipt"]["reservation"]
                != static.report["operation_receipt"]["reservation"]):
            raise ValueError("primary arms did not match their fixed update and resident budgets")
        if any(c["head_example_calls"] != split_usage["head_example_calls"] for c in (observed_split, observed_static)):
            raise ValueError("evolution receipts disagree with observed real Head forwards")
        pooled, observed_pooled = _measure(train_cell_head, pooled_train, pooled_cal, holdouts, config=replace(head_config, seed=seed))
        pooled_snapshot = bootstrap_snapshot([RouterCellV1("pooled", pooled, 1, _groups(pooled_train, pooled_cal, holdouts))],
            None, {}, directory / "pooled", budget, provider)
        arms, losses, correct, predictions = {}, {}, {}, {}
        for arm, graph in (("parent", parent), ("split", split), ("static", static), ("pooled_retrain", pooled_snapshot)):
            arms[arm], losses[arm], correct[arm], predictions[arm] = _evaluation(graph, holdouts, provider, seed, arm, ledger)
            arms[arm]["reload"] = _reload_check(graph, holdouts["future_1"], provider, seed, arm,
                                                 ledger, predictions[arm]["future_1"])
            arms[arm]["resident_tensor_bytes"] = graph.report["resident_tensor_bytes"]
            arms[arm]["snapshot_manifest_sha256"] = graph.manifest_sha256
        comparisons = {name: {"split_minus_static_nll": paired_interval(losses["split"][name], losses["static"][name]),
            "split_minus_static_accuracy": paired_interval(correct["split"][name], correct["static"][name]),
            "split_minus_pooled_nll": paired_interval(losses["split"][name], losses["pooled_retrain"][name]),
            "split_minus_pooled_accuracy": paired_interval(correct["split"][name], correct["pooled_retrain"][name])}
            for name in HOLDOUTS}
        mechanics = _mechanics(parent, split, static, encoded, holdouts, directory, budget, provider,
                              evolution_config, seed, ledger, predictions["parent"]["future_1"])
        reports.append({"seed": seed, "arms": arms, "comparisons": comparisons, "mechanics": mechanics,
            "matched_actual_usage": split_usage, "split_operation_receipt": split.report["operation_receipt"],
            "observed_split_forward_counts": observed_split, "observed_static_forward_counts": observed_static,
            "observed_common_parent_forward_counts": common_calls, "observed_pooled_forward_counts": observed_pooled,
            "static_operation_receipt": static.report["operation_receipt"],
            "common_parent_Head_reports": {c.cell_id: c.head.report for c in cells},
            "common_parent_Router_accounting": router.report["execution_accounting"],
            "pooled_Head_report": pooled.report, "primary_budget_match_exact": True})
        print(json.dumps({"seed": seed, "comparisons": comparisons, "matched_usage": split_usage}), flush=True)
    if code_identity() != plan["code_file_sha256"] or sha((target / "plan.json").read_bytes()) != plan_sha:
        raise ValueError("code or precommitted plan changed during experiment")
    if model_tensor_digest(owner._model) != feature_manifest["encoder_tensor_sha256"]:
        raise ValueError("shared Encoder changed during local evolution")
    ledger_sha = _write(target / "prediction_ledger.json", ledger)
    report = {"schema": "hepta.real-cell-evolution-probe.v1", "plan_sha256": plan_sha,
        "cohort_manifest_sha256": cohort_manifest_sha, "feature_manifest_sha256": feature_sha,
        "prediction_ledger_sha256": ledger_sha, "candidate": "granite97m", "encoder": owner.accounting,
        "feature_identity": asdict(owner.identity), "encoder_unchanged": True, "seeds": reports,
        "elapsed_ms": (time.perf_counter() - began) * 1000, "rss_before": rss_before, "rss_after": rss_observation(),
        "scope": {"historical_source_families": 1, "prospective_windows": 0, "memory_task": False,
            "autonomous_split_trigger": False, "independent_evaluator": False, "production_source_authentication": False,
            "cross_node": False, "production_activation_allowed": False}, "authority": "DENY_ALL", "mode": "SHADOW_ONLY"}
    _write(target / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "inventory-sha256", "cohorts", "archive", "output"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--operator-accepted-terms", action="store_true", required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threads", type=int, default=4)
    run_probe(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
