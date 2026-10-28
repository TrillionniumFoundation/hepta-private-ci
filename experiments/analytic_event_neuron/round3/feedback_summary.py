"""Predeclared paired utility and actual delivered-head calibration summaries."""

import gzip
import json
import math
from pathlib import Path

import numpy as np

from ..statistics import paired_interval
from .feedback import ARMS
from .runtime_feedback import file_sha


CONTRASTS = (("event", "gaussian"), ("analytic", "numeric"), ("analytic", "gaussian"),
             ("analytic", "history"), ("analytic", "zero"), ("analytic", "reset"),
             ("event", "quantized"), ("gaussian", "probit"))


def summarize(run_dir, seeds=None, count=None, replicates=None):
    from . import freeze
    root = Path(run_dir)
    frozen = freeze.verify(root)
    protocol = json.loads((freeze.PROJECT / "PROTOCOL.json").read_text())["feedback"]
    settings = protocol["statistics"]
    seeds = protocol["seeds"] if seeds is None else list(seeds)
    count = protocol["confirmation_rows"] if count is None else count
    replicates = settings["bootstrap_replicates"] if replicates is None else replicates
    if (seeds != protocol["seeds"] or count != protocol["confirmation_rows"]
            or replicates != settings["bootstrap_replicates"]
            or tuple(tuple(x) for x in protocol["primary_contrasts"] + protocol["secondary_contrasts"]) != CONTRASTS
            or settings["bootstrap_seed"] != 28102840 or settings["family_alpha"] != .05
            or settings["primary_family_size"] != 3 or settings["superiority_margin"] != .01
            or settings["event_noninferiority_margin"] != .01):
        raise ValueError("Analysis differs from frozen feedback registration")
    arrays, all_rows, receipts = {arm: [] for arm in ARMS}, {arm: [] for arm in ARMS}, []
    for seed in seeds:
        scope = root / "feedback_confirmation" / f"seed_{seed}"
        summary, audit = [json.loads((scope / name).read_text()) for name in ("SUMMARY.json", "AUDIT.json")]
        expected_model = frozen["artifacts_sha256"][f"feedback_prepared/seed_{seed}/MODELS.json"]
        if (not audit["passed"] or audit["dataset_split"] != "confirmation" or summary["seed"] != seed
                or summary["model_file_sha256"] != expected_model
                or file_sha(scope / "ROWS.json.gz") != summary["rows_sha256"]
                or file_sha(scope / "DATA.npz") != summary["data_sha256"]):
            raise ValueError("Unverified feedback scope")
        with gzip.open(scope / "ROWS.json.gz", "rt") as stream:
            rows = json.load(stream)
        reference = None
        for arm in ARMS:
            selected = sorted([r for r in rows if r["arm"] == arm], key=lambda r: r["case"])
            identities = [r["case"] for r in selected]
            data_seed = protocol["data_offset"] + 100 * seed + 3
            expected_ids = {f"feedback3:confirmation:{data_seed}:{i}" for i in range(count)}
            if len(selected) != count or set(identities) != expected_ids or (reference is not None and identities != reference):
                raise ValueError("Unpaired trajectory coverage")
            reference = identities
            arrays[arm].append(np.asarray([r["utility"] for r in selected]))
            all_rows[arm].extend(selected)
        receipts.append({"seed": seed, "episodes": audit["episodes"],
            "typed_ticks_replayed": audit["typed_ticks_replayed"], "sparse_ticks_replayed": audit["sparse_ticks_replayed"],
            "evaluation_wall_ns": summary["wall_ns"], "evaluation_cpu_ns": summary["cpu_ns"],
            "native_requests": summary["native_requests"], "native_roundtrip_ns": summary["native_roundtrip_ns"],
            "audit_wall_ns": audit["wall_ns"], "audit_native_roundtrip_ns": audit["replay_cost"]["native_roundtrip_ns"]})
    contrasts = {}
    for index, (candidate, baseline) in enumerate(CONTRASTS):
        delta = np.asarray(arrays[candidate]) - np.asarray(arrays[baseline])
        alpha = .05 / 3 if index < 3 else .05
        contrast = paired_interval(delta, replicates, 28102840 + index, alpha)
        contrast.update(candidate=candidate, baseline=baseline, family_adjusted=index < 3,
            empirical_superiority_001=bool(contrast["interval"][0] > .01 and np.all(delta.mean(1) > 0)),
            empirical_noninferiority_001=bool(contrast["interval"][0] > -.01 and np.all(delta.mean(1) > -.01)),
            population_or_production_guarantee=False)
        contrasts[candidate + "_vs_" + baseline] = contrast
    metrics = {}
    for arm, rows in all_rows.items():
        probability = np.asarray([r["stages"][0]["law"]["probabilities"] for r in rows])
        labels, covered = [], []
        for row in rows:
            stage, error = row["stages"][0], row["terminal_error"]
            if stage["runtime"] is None:
                lower, upper = -math.sqrt(stage["public"]["repair_cost"]), math.sqrt(stage["public"]["repair_cost"])
            else:
                _, _, lower, upper = stage["runtime"]["native"]["head"]["parameters_q24_decoded"]
            labels.append(0 if error <= lower else 2 if error > upper else 1)
            covered.append(abs(error - stage["law"]["mean"]) <= 1.959963984540054 * math.sqrt(stage["law"]["variance"]))
        labels = np.asarray(labels)
        selected = probability[np.arange(len(labels)), labels]
        zeros = int(np.sum(selected == 0))
        confidence, correct = probability.max(1), probability.argmax(1) == labels
        assignment = np.minimum((10 * confidence).astype(int), 9)
        ece = sum(np.mean(assignment == j) * abs(float(confidence[assignment == j].mean()) - float(correct[assignment == j].mean()))
                  for j in range(10) if np.any(assignment == j))
        classwise = []
        for category in range(3):
            bins = np.minimum((10 * probability[:, category]).astype(int), 9)
            classwise.append(sum(np.mean(bins == j) * abs(float(probability[bins == j, category].mean())
                - float(np.mean(labels[bins == j] == category))) for j in range(10) if np.any(bins == j)))
        metrics[arm] = {key: float(np.mean([row[key] for row in rows])) for key in ("utility", "squared_error", "cost", "wall_ns")}
        metrics[arm].update(episodes=len(rows), waits=sum("wait" in row["actions"] for row in rows),
            repairs=sum("repair" in row["actions"] for row in rows), initial_terminal_top_label_ece=ece,
            initial_terminal_classwise_ece=float(np.mean(classwise)),
            initial_95_gaussian_coverage=float(np.mean(covered)),
            initial_terminal_brier=float(np.mean(np.sum((probability - np.eye(3)[labels]) ** 2, axis=1))),
            initial_terminal_nll=None if zeros else float(-np.log(selected).mean()),
            true_event_zero_probability_count=zeros,
            nll_definition="Actual delivered head probabilities, no clipping; mean null if any zero-mass realized event",
            logical_unit_events=sum(stage["runtime"]["logical_unit_events"] for row in rows for stage in row["stages"] if stage["runtime"]),
            packet_bytes=sum(stage["runtime"]["packet_bytes"] for row in rows for stage in row["stages"] if stage["runtime"]))
    mechanism = {}
    for candidate, baseline in CONTRASTS:
        a, b = all_rows[candidate], all_rows[baseline]
        mechanism[candidate + "_vs_" + baseline] = {
            "action_disagreements": sum(x["actions"] != y["actions"] for x, y in zip(a, b)),
            "final_output_disagreements": sum(x["delivered"] != y["delivered"] for x, y in zip(a, b)),
            "maximum_initial_probability_difference": max(float(np.max(np.abs(np.asarray(x["stages"][0]["law"]["probabilities"])
                - y["stages"][0]["law"]["probabilities"]))) for x, y in zip(a, b)),
            "mean_squared_error_reduction": float(np.mean([y["squared_error"] - x["squared_error"] for x, y in zip(a, b)])),
            "mean_paid_cost_increase": float(np.mean([x["cost"] - y["cost"] for x, y in zip(a, b)]))}
    freeze.verify(root)
    return {"schema": "hepta.paid-feedback.results.v3", "complete": True, "arms": metrics,
        "source_commit": frozen["source_commit"], "frozen_source_and_model_binding": True,
        "training_seeds": seeds, "independent_confirmation_trajectories": len(seeds) * count,
        "initial_terminal_event_labels": len(seeds) * count * len(ARMS),
        "contrasts": contrasts, "mechanism": mechanism, "execution_receipts": receipts,
        "unique_trajectories": len(seeds) * count, "control_executions": len(seeds) * count * len(ARMS),
        "actual_runtime_profile_scored": True, "production_promotion": False,
        "all_terms_public_and_target_only_postdelivery": True,
        "task_law": "Gaussian static hidden error; paid independent second noisy sensor",
        "probability_semantics": "Terminal remaining-error interval at initial public conditioning, not first passage or repair-gain probability",
        "action_cost_is_not_cpu_time_or_dollars": True,
        "memory_ablation_scope": "Same Q24 posterior repair amplitude and planning formula; zero/reset affect sparse decision representation, each readout refitted"}
