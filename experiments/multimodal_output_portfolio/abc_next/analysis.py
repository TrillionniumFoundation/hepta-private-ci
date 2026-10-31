"""Paired complete-census inference for the frozen new-source experiment."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ..abc_recovery.analysis import ce_interaction
from ..abc_recovery.base_recovery import file_sha, write_json
from ..abc_recovery.control import PLANS
from ..abc_recovery.statistics import (CrossedBootstrap, crossed_bootstrap, loss_tails,
                                       paired_comparison, summarize_utility)
from ..abc_recovery.trees import METRICS
from ..v7.data import VIEWS
from .execute import POLICIES
from .settings import ARMS, MANIFEST, SEEDS


ADDED = ("net_utility", "continuation_actions", "semantic_then_stop")
BASELINE = "selected_nonfeedback"
PRIMARY = ((("output_ndu", "fixed"), ("output_mean", "fixed")),
           (("output_ndu", "feedback"), ("output_ndu", BASELINE)))


def load_cubes(directory, protocol):
    result = json.loads((directory / "result.json").read_text())
    interval = result["source_range"]
    if interval != protocol["source_ranges"][result["phase"]]:
        raise ValueError("Execution does not match its frozen source range")
    if file_sha(MANIFEST) != protocol["resources"]["manifest_sha256"]:
        raise ValueError("Frozen source identity manifest changed")
    count, scenarios, start = interval["count"], interval["scenarios"], interval["start"]
    shape = (len(SEEDS), count, len(VIEWS), scenarios)
    conditions = [(arm, policy) for arm in ARMS for policy in (*POLICIES, BASELINE)]
    cubes = {observer: {c: {m: np.empty(shape) for m in (*METRICS, *ADDED)} for c in conditions}
             for observer in ("primary", "secondary")}
    fitted_path = Path(protocol["controllers_directory"]) / "result.json"
    if file_sha(fitted_path) != protocol["controllers_result_sha256"]:
        raise ValueError("Frozen controller choices changed before analysis")
    fitted = json.loads(fitted_path.read_text())
    selected = {(r["seed"], r["arm"]): r["selection"]["selected_nonfeedback"] for r in fitted["controllers"]}
    source_ids = json.loads(MANIFEST.read_text())["roles"][interval["role"]]["source_ids"]
    expected = [(case, view, scenario) for view in VIEWS for case in range(start, start + count)
                for scenario in range(scenarios)]
    seen, plan_counts = set(), {}
    lengths = np.array([len(p) for p in PLANS])
    for row in result["models"]:
        seed, arm = row["seed"], row["arm"]
        key = (seed, arm)
        if key in seen or key not in selected:
            raise ValueError("Duplicate or unknown trained model in evaluation")
        seen.add(key)
        path = Path(row["directory"]) / "data.pt"
        if file_sha(path) != row["data_sha256"]:
            raise ValueError("Observed policy census changed")
        data = torch.load(path, weights_only=True)
        actual = list(zip(data["cases"], data["views"], data["scenarios"]))
        if actual != expected or tuple(data["policies"]) != POLICIES:
            raise ValueError("Incomplete, reordered or duplicated task/policy census")
        if len(data["source_ids"]) != len(expected) or any(tuple(ids) != tuple(source_ids[2 * case:2 * case + 2]) for case, ids in zip(data["cases"], data["source_ids"])):
            raise ValueError("Source identities differ from registered source groups")
        plans = data["paths"].numpy()
        if plans.shape != (len(expected), len(POLICIES)) or plans.dtype.kind not in "iu" or (plans < 0).any() or (plans >= 21).any():
            raise ValueError("Invalid actual terminal path census")
        for policy in (*POLICIES, BASELINE):
            index = POLICIES.index(selected[key] if policy == BASELINE else policy)
            choices = plans[:, index]
            plan_counts[f"{seed}/{arm}/{policy}"] = np.bincount(choices, minlength=21).tolist()
            for observer in cubes:
                if any(data["metrics"][observer][m].shape != plans.shape for m in METRICS):
                    raise ValueError("Metric and registered policy census dimensions differ")
                values = {m: data["metrics"][observer][m][:, index].numpy().astype(np.float64) for m in METRICS}
                values["continuation_actions"] = lengths[choices]
                values["net_utility"] = values["utility"] - .002 * lengths[choices]
                values["semantic_then_stop"] = (choices == 1).astype(float)
                for metric, vector in values.items():
                    if vector.shape != (len(expected),) or not np.isfinite(vector).all():
                        raise ValueError("Missing/nonfinite observed metric")
                    cubes[observer][(arm, policy)][metric][SEEDS.index(seed)] = vector.reshape(8, count, scenarios).transpose(1, 0, 2)
    if seen != {(seed, arm) for seed in SEEDS for arm in ARMS}:
        raise ValueError("One or more registered generator cells is missing")
    return cubes, plan_counts


def source_only_plan(plan):
    seeds = np.tile(np.arange(len(SEEDS), dtype=np.int64), (len(plan.seed_indices), 1))
    sources = plan.source_indices.copy()
    identity = hashlib.sha256(f"{seeds.shape}:{sources.shape}".encode() + seeds.astype("<i8").tobytes() + sources.astype("<i8").tobytes()).hexdigest()
    return CrossedBootstrap(seeds, sources, plan.random_seed, identity)


def analyze(directory, protocol_path, output):
    protocol = json.loads(protocol_path.read_text())
    execution = json.loads((directory / "result.json").read_text())
    if execution["status"] != "completed" or execution["protocol_sha256"] != file_sha(protocol_path):
        raise ValueError("Complete same-protocol execution is required")
    cubes, plans = load_cubes(directory, protocol)
    count = execution["source_range"]["count"]
    bootstrap = crossed_bootstrap(5, count, replicates=4000, seed=2026102507)
    conditional = source_only_plan(bootstrap)
    contrasts = list(PRIMARY)
    contrasts += [((a, "feedback"), (a, b)) for a in ARMS for b in ("fixed", "legacy")]
    contrasts += [(("output_ndu", p), ("sft_continuation", p)) for p in ("fixed", "feedback")]
    contrasts += [(("output_ndu", "feedback"), ("output_mean", "feedback")),
                  (("output_ndu", "feedback"), ("output_ndu", "one_shot")),
                  (("output_ndu", "feedback"), ("output_ndu", "static"))]
    observers = {}
    for name, cells in cubes.items():
        summary = {}
        for condition, metrics in cells.items():
            key = "/".join(condition)
            summary[key] = {"net_utility": summarize_utility(metrics["net_utility"]),
                            "raw_utility": summarize_utility(metrics["utility"]),
                            "mean_metrics": {m: float(v.mean()) for m, v in metrics.items()},
                            "joint_loss_tails": loss_tails(metrics["joint_loss"]),
                            "by_view": {view: {"net_joint_CE": summarize_utility(metrics["net_utility"][:, :, i:i + 1])["joint_ce"],
                                               "joint_success": float(metrics["joint_fact_correct"][:, :, i].mean()),
                                               "complete": float(metrics["required_output_complete"][:, :, i].mean()),
                                               "mean_loss": float(metrics["joint_loss"][:, :, i].mean())}
                                        for i, view in enumerate(VIEWS)}}
        comparisons = []
        for candidate, reference in contrasts:
            primary = (candidate, reference) in PRIMARY
            a, b = cells[candidate], cells[reference]
            ce = paired_comparison(a["net_utility"], b["net_utility"], confidence=.975 if primary else .95, bootstrap=bootstrap)
            success = paired_comparison(a["joint_fact_correct"], b["joint_fact_correct"], estimand="success_rate", bootstrap=bootstrap)
            row = {"candidate": candidate, "reference": reference, "primary_contrast": primary,
                   "net_joint_CE": ce, "joint_success": success}
            if primary:
                fixed = paired_comparison(a["net_utility"], b["net_utility"], confidence=.975, bootstrap=conditional)
                fixed["bootstrap"]["resampling"] = "resample only source-pair axis; all five fitted models fixed; preserve all views/scenarios"
                fixed["bootstrap"]["scope"] = "conditional on these exact five trained models, not a training-seed population interval"
                row["fixed_five_seed_source_interval"] = fixed
            comparisons.append(row)
        observers[name] = {"cells": summary, "comparisons": comparisons,
            "risk_vs_mean_interaction": ce_interaction(*(cells[c]["net_utility"] for c in
                (("output_ndu", "feedback"), ("output_ndu", "fixed"), ("output_mean", "feedback"), ("output_mean", "fixed"))), bootstrap=bootstrap),
            "risk_vs_sft_interaction": ce_interaction(*(cells[c]["net_utility"] for c in
                (("output_ndu", "feedback"), ("output_ndu", "fixed"), ("sft_continuation", "feedback"), ("sft_continuation", "fixed"))), bootstrap=bootstrap)}
        observers[name]["risk_vs_mean_interaction"].update({
            "estimand": "[CE(output_ndu,feedback)-CE(output_ndu,fixed)]-[CE(output_mean,feedback)-CE(output_mean,fixed)]",
            "positive_means": "feedback CE increment is greater under output_ndu than output_mean; neither increment is necessarily positive",
            "cells_in_signed_order": [["output_ndu", "feedback"], ["output_ndu", "fixed"],
                                      ["output_mean", "feedback"], ["output_mean", "fixed"]]})
    primary_results = observers["primary"]["comparisons"][:2]
    report = {"schema": "hepta.abc-next.new-source-analysis.v1", "phase": execution["phase"],
        "protocol_sha256": file_sha(protocol_path), "execution_result_sha256": file_sha(directory / "result.json"),
        "source_pairs": count, "training_seeds": SEEDS, "views": VIEWS,
        "scenarios_per_source": execution["source_range"]["scenarios"], "observers": observers,
        "plan_counts": plans, "primary_positive_lower_endpoints": [r["net_joint_CE"]["interval"][0] > 0 for r in primary_results],
        "qualification_is_formal_test": False, "is_formal_test": execution["phase"] == "test",
        "source_rows_are_independent_n": False,
        "unobserved_writer_clusters_available": False,
        "all_blockers_closed": False, "global_optimum_certified": False,
        "raw_data_archival_required": False, "empirical_tail_and_few_seed_interval_limits_apply": True}
    write_json(output, report)
    print(json.dumps({"phase": execution["phase"], "source_pairs": count,
                      "primary": [{"candidate": r["candidate"], "reference": r["reference"],
                                   "gain": r["net_joint_CE"]["gain"], "interval": r["net_joint_CE"]["interval"]}
                                  for r in primary_results]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("directory", "protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    analyze(args.directory, args.protocol, args.output)


if __name__ == "__main__":
    main()
