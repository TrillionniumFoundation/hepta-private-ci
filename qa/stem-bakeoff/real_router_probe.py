"""Source-separated, fixed-budget routing on a pinned real frozen Encoder.

This measures a routing mechanism on historical news classification. It is not
a longitudinal memory evaluation or independently qualified deployment claim.
The complete plan is written before loading the checkpoint or scoring holdouts.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from cell_head_training import (HeadCohortV1, HeadTrainingConfigV1,
                                load_head_artifact, save_head_artifact,
                                train_cell_head)
from feature_bundle import FeatureBundleV1
from prepare_news_cohorts import canonical, load_cohorts, sha
from real_encoder import CANDIDATES, FrozenRealEncoder
from real_model_bakeoff import code_identity, model_tensor_digest, rss_observation

SEEDS = (7, 17, 29)
HOLDOUTS = ("future_1", "future_2", "ood")


def split_indices(rows):
    """Partition whole source groups without examining labels or features."""
    if len({r["source_group_id"] for r in rows["train"]}) != 256:
        raise ValueError("this frozen plan requires 256 distinct training stories")
    if len({r["source_group_id"] for r in rows["calibration"]}) != 128:
        raise ValueError("this frozen plan requires 128 distinct calibration stories")

    def order(name):
        return sorted(range(len(rows[name])), key=lambda i: hashlib.sha256(
            ("hepta-router-v1/" + rows[name][i]["source_group_id"]).encode()).digest())

    train, cal = order("train"), order("calibration")
    return {"head_a": ("train", train[:96]), "head_b": ("train", train[96:192]),
            "router_train": ("train", train[192:]),
            "head_calibration": ("calibration", cal[:64]),
            "router_calibration": ("calibration", cal[64:]),
            **{name: (name, list(range(len(rows[name])))) for name in HOLDOUTS}}


def subset(encoded, rows, source_name, indices):
    features = torch.cat([b.read_global() for b in encoded[source_name]])
    sources = tuple(s for b in encoded[source_name] for s in b.source_record_digests)
    identity = encoded[source_name][0].identity
    missing = torch.ones((len(indices), 5), dtype=torch.bool)
    missing[:, 0] = False
    bundle = FeatureBundleV1.from_tensors(global_features=features[indices],
        source_record_digests=tuple(sources[i] for i in indices),
        identity=identity, missing_mask=missing)
    selected = [rows[source_name][i] for i in indices]
    return HeadCohortV1(bundle, tuple(r["label"] for r in selected),
                        tuple(r["source_group_id"] for r in selected))


def probability_metrics(probabilities, labels):
    p = probabilities.detach().double().cpu().numpy()
    y = np.asarray(labels, dtype=np.int64)
    if p.shape != (len(y), 4) or not np.isfinite(p).all():
        raise ValueError("invalid four-class prediction matrix")
    losses = -np.log(np.maximum(p[np.arange(len(y)), y], 1e-12))
    correct = (p.argmax(axis=1) == y).astype(float)
    return {"rows": len(y), "accuracy": float(correct.mean()),
            "nll": float(losses.mean())}, losses, correct


def paired_interval(candidate, baseline):
    """Descriptive paired story bootstrap; no winner or qualification decision."""
    difference = np.asarray(candidate) - np.asarray(baseline)
    rng = np.random.default_rng(211)
    resampled = difference[rng.integers(0, len(difference), (2000, len(difference)))].mean(axis=1)
    return {"difference": float(difference.mean()),
            "descriptive_95_percent_interval": np.quantile(resampled, [0.025, 0.975]).tolist(),
            "resampling_unit": "one unique source story", "samples": 2000,
            "multiplicity_adjusted": False}


def run_probe(*, candidate, snapshot, inventory_sha256, cohorts, archive,
              output, operator_accepted_terms, batch_size=16, threads=4):
    from cell_router_training import RouterCellV1, RouterTrainingConfigV1, train_cell_router
    from cell_router_artifact import load_router_artifact, save_router_artifact

    if (candidate not in CANDIDATES or operator_accepted_terms is not True
            or not 1 <= batch_size <= 32 or not 1 <= threads <= 8):
        raise ValueError("invalid fixed-candidate research plan")
    torch.set_num_threads(threads)
    torch.manual_seed(7)
    manifest = (Path(cohorts) / "manifest.json").read_bytes()
    dataset, rows = load_cohorts(cohorts, expected_manifest_sha256=sha(manifest), archive=archive)
    partitions = split_indices(rows)
    target = Path(output)
    target.mkdir(parents=True, exist_ok=False)
    head_config = HeadTrainingConfigV1(task_count=4, mode="gated", steps=200,
                                       learning_rate=0.2, seed=7)
    router_config = RouterTrainingConfigV1(steps=200, learning_rate=0.1,
                                           seed=7, top_k=1, budget_units=1)
    plan = {"schema": "hepta.real-cell-router-plan.v1", "candidate": candidate,
        "checkpoint_revision": CANDIDATES[candidate]["revision"],
        "checkpoint_inventory_sha256": inventory_sha256,
        "dataset_manifest_sha256": sha(manifest), "source": dataset,
        "seeds": list(SEEDS), "head_config": asdict(head_config),
        "router_config": asdict(router_config), "partitions": {
            name: {"original_split": source, "indices": indices,
                   "source_groups": [rows[source][i]["source_group_id"] for i in indices]}
            for name, (source, indices) in partitions.items()},
        "head_count": 2, "cost_units_per_head_call": 1,
        "selected_heads_per_record": 1, "max_tokens": 128,
        "batch_size": batch_size, "encoder_cpu_threads": threads,
        "comparators": ["fixed_a", "fixed_b", "fixed_best_on_router_calibration", "pooled_head", "learned"],
        "baseline_selection": "lowest router-calibration NLL; cell-id tie break",
        "holdouts_select_hyperparameters_or_winner": False,
        "head_call_budget": "one selected Head call per row in every arm",
        "same_pool_controls": "fixed_a, fixed_b, fixed_best_on_router_calibration share both frozen Heads",
        "pooled_baseline": "one same-architecture Head; all 256 training and 128 calibration records",
        "total_parameter_or_training_compute_matched": False,
        "router_overhead_accounted_separately": True,
        "claim": "historical news classification mechanism only",
        "code_file_sha256": code_identity()}
    (target / "plan.json").write_bytes(canonical(plan) + b"\n")
    start = time.perf_counter()
    rss_before = rss_observation()
    owner = FrozenRealEncoder(candidate=candidate, snapshot=snapshot,
        revision=plan["checkpoint_revision"], expected_inventory_sha256=inventory_sha256,
        operator_accepted_terms=True, profile="text", max_tokens=128,
        scope_id="memory-router-research-v1")
    encoder_before = model_tensor_digest(owner._model)
    encoded, receipts, feature_manifests = {}, [], {}
    for name, split in rows.items():
        encoded[name] = []
        feature_manifests[name] = []
        for offset in range(0, len(split), batch_size):
            batch = split[offset:offset + batch_size]
            bundle = owner.encode_text([r["text"] for r in batch], source_records=batch)
            encoded[name].append(bundle)
            feature_manifests[name].append(bundle.manifest())
            receipts.append({"split": name, "offset": offset, **owner.last_receipt})
        print(json.dumps({"encoded": name, "rows": len(split), "candidate": candidate}), flush=True)
    encoder_after = model_tensor_digest(owner._model)
    if encoder_before != encoder_after:
        raise ValueError("frozen Encoder changed during the experiment")
    encoded_cohorts = {name: subset(encoded, rows, source, indices)
                       for name, (source, indices) in partitions.items()}
    (target / "feature_manifests.json").write_bytes(canonical(feature_manifests) + b"\n")
    holdouts = {name: encoded_cohorts[name] for name in HOLDOUTS}
    pooled_train = subset(encoded, rows, "train", list(range(len(rows["train"]))))
    pooled_calibration = subset(encoded, rows, "calibration", list(range(len(rows["calibration"]))))
    seed_reports, ledger = [], []
    for seed in SEEDS:
        seed_dir = target / f"seed-{seed}"
        seed_dir.mkdir()
        cells, head_artifacts = [], {}
        for index, name in enumerate(("head_a", "head_b")):
            trained = train_cell_head(encoded_cohorts[name], encoded_cohorts["head_calibration"],
                holdouts, config=HeadTrainingConfigV1(**{**asdict(head_config), "seed": seed + index}))
            path = seed_dir / name
            artifact = save_head_artifact(trained, path)
            restored = load_head_artifact(path, expected_manifest_sha256=artifact["manifest_sha256"],
                                          expected_identity=owner.identity)
            if not torch.equal(trained.predict_task(holdouts["future_1"].bundle)["task_probabilities"],
                               restored.predict_task(holdouts["future_1"].bundle)["task_probabilities"]):
                raise ValueError("Head artifact reload changed exact predictions")
            source_groups = {"train": encoded_cohorts[name].source_group_ids,
                             "calibration": encoded_cohorts["head_calibration"].source_group_ids,
                             **{h: c.source_group_ids for h, c in holdouts.items()}}
            cells.append(RouterCellV1(name, restored, 1, source_groups))
            head_artifacts[name] = {**artifact, "directory": str(path.relative_to(target))}
        pooled = train_cell_head(pooled_train, pooled_calibration, holdouts,
            config=HeadTrainingConfigV1(**{**asdict(head_config), "seed": seed}))
        pooled_artifact = save_head_artifact(pooled, seed_dir / "pooled_head")
        pooled_restored = load_head_artifact(seed_dir / "pooled_head",
            expected_manifest_sha256=pooled_artifact["manifest_sha256"], expected_identity=owner.identity)
        if not torch.equal(pooled.predict_task(holdouts["future_1"].bundle)["task_probabilities"],
                           pooled_restored.predict_task(holdouts["future_1"].bundle)["task_probabilities"]):
            raise ValueError("pooled Head artifact reload changed exact predictions")
        pooled = pooled_restored
        began = time.perf_counter()
        router = train_cell_router(encoded_cohorts["router_train"],
            encoded_cohorts["router_calibration"], holdouts, cells,
            config=RouterTrainingConfigV1(**{**asdict(router_config), "seed": seed}))
        router_training_ms = 1000 * (time.perf_counter() - began)
        router_artifact = save_router_artifact(router, seed_dir / "router")
        restored_router = load_router_artifact(seed_dir / "router",
            expected_manifest_sha256=router_artifact["manifest_sha256"],
            expected_identity=owner.identity, cells=cells)
        cal = encoded_cohorts["router_calibration"]
        cal_scores = {cell.cell_id: probability_metrics(router.predict_task(cal.bundle, cells,
            fixed_cell_ids=(cell.cell_id,))["task_probabilities"], cal.labels)[0]["nll"] for cell in cells}
        fixed_best = min(cal_scores, key=lambda name: (cal_scores[name], name))
        split_reports = {}
        for split_name, cohort in holdouts.items():
            arms, row_losses, row_correct = {}, {}, {}
            for arm, fixed in (("fixed_a", ("head_a",)), ("fixed_b", ("head_b",)),
                               ("fixed_best_on_router_calibration", (fixed_best,)),
                               ("pooled_head", None), ("learned", None)):
                began = time.perf_counter()
                if arm == "pooled_head":
                    prediction = pooled.predict_task(cohort.bundle)
                    prediction.update({"head_example_calls": len(cohort.labels),
                        "actual_cost_units": len(cohort.labels), "router_forward_calls": 0,
                        "head_module_invocations": {"pooled_head": 1},
                        "routes": [{"source_record_digest": source, "selected": ["pooled_head"],
                                    "actual_calls": ["pooled_head"], "actual_cost_units": 1,
                                    "budget_units": 1, "route_mode": "pooled_fixed"}
                                   for source in cohort.bundle.source_record_digests]})
                else:
                    prediction = router.predict_task(cohort.bundle, cells, fixed_cell_ids=fixed)
                elapsed = 1000 * (time.perf_counter() - began)
                metrics, losses, correct = probability_metrics(prediction["task_probabilities"], cohort.labels)
                arms[arm] = {**metrics, "observed_inference_ms": elapsed}
                row_losses[arm], row_correct[arm] = losses, correct
                ledger.append({"seed": seed, "split": split_name, "arm": arm,
                    "feature_bundle_sha256": cohort.bundle.bundle_digest,
                    "source_group_ids": list(cohort.source_group_ids),
                    "labels": list(cohort.labels),
                    "task_probabilities": prediction["task_probabilities"].tolist(),
                    **{k: v for k, v in prediction.items()
                       if k != "task_probabilities" and not isinstance(v, torch.Tensor)}})
                if arm == "learned":
                    replay = restored_router.predict_task(cohort.bundle, cells)
                    if not torch.equal(prediction["task_probabilities"], replay["task_probabilities"]):
                        raise ValueError("Router artifact reload changed exact predictions")
            split_reports[split_name] = {"arms": arms,
                "learned_minus_calibration_selected_fixed_nll": paired_interval(
                    row_losses["learned"], row_losses["fixed_best_on_router_calibration"]),
                "learned_minus_calibration_selected_fixed_accuracy": paired_interval(
                    row_correct["learned"], row_correct["fixed_best_on_router_calibration"]),
                "learned_minus_pooled_head_nll": paired_interval(row_losses["learned"], row_losses["pooled_head"]),
                "learned_minus_pooled_head_accuracy": paired_interval(row_correct["learned"], row_correct["pooled_head"])}
        seed_reports.append({"seed": seed, "head_artifacts": head_artifacts,
            "head_reports": {c.cell_id: c.head.report for c in cells},
            "pooled_head_report": pooled.report,
            "pooled_head_artifact": {**pooled_artifact, "directory": str((seed_dir / "pooled_head").relative_to(target))},
            "router_artifact": {**router_artifact, "directory": str((seed_dir / "router").relative_to(target))},
            "router_report": router.report, "router_training_ms": router_training_ms,
            "fixed_baseline_selected_on_calibration": fixed_best,
            "fixed_calibration_nll": cal_scores, "holdouts": split_reports,
            "head_and_router_reload_exact": True})
        print(json.dumps({"seed": seed, "holdouts": split_reports}), flush=True)
    report = {"schema": "hepta.real-cell-router-probe.v1", "plan_sha256": sha(canonical(plan) + b"\n"),
        "candidate": candidate, "encoder": owner.accounting,
        "feature_identity": asdict(owner.identity), "encoder_tensor_sha256": encoder_after,
        "encoder_unchanged": True, "encoder_forward_receipts": receipts,
        "single_encoding_reused_by_all_heads_and_seeds": True,
        "seeds": seed_reports, "elapsed_ms": (time.perf_counter() - start) * 1000,
        "rss_before": rss_before, "rss_after": rss_observation(),
        "qualification": {"historical_source_families": 1, "prospective_windows": 0,
            "independent_evaluator": False, "memory_task": False,
            "topology_evolution": False, "cross_node": False,
            "production_activation_allowed": False},
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY"}
    (target / "prediction_ledger.json").write_bytes(canonical(ledger) + b"\n")
    report["prediction_ledger_sha256"] = sha((target / "prediction_ledger.json").read_bytes())
    (target / "report.json").write_bytes(canonical(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=tuple(CANDIDATES), required=True)
    for name in ("snapshot", "inventory-sha256", "cohorts", "archive", "output"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--operator-accepted-terms", action="store_true", required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--threads", type=int, default=4)
    run_probe(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
