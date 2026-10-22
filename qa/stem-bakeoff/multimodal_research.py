"""Reproducible frozen-Stem/private-Head multimodal research, with real evidence.

Write the complete plan before training. Development NLL selects step budgets;
calibration alone selects temperature. The test set never selects a model,
threshold or reporting winner. A failed research screen is a valid experiment.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import torch

from cell_head_training import (HeadCohortV1, HeadTrainingConfigV1, TEMPERATURES,
    load_head_artifact, save_head_artifact, train_cell_head)
from feature_bundle import FeatureBundleV1
from multimodal_cohorts import load_cohorts
from multimodal_features import ARMS, FUSION, bank_code_identity, load_bank, pair_features
from prediction_ledger import (LedgerIdentityV1, PredictionLedgerV1,
    ResearchQualificationV1, assess_multimodal_research, assess_research_qualification,
    canonical, cluster_intervals, load_prediction_ledger, paired_intervention_summary,
    save_prediction_ledger, sha)
from real_model_bakeoff import rss_observation

MODES = ("linear", "gated")
STEPS = (200, 1000, 3000)
INTERVENTIONS = ("shuffled_image", "missing_text", "missing_image")


def research_code_identity():
    names = ("multimodal_research.py", "prediction_ledger.py", "cell_head_training.py",
             "native_latent.py", "multimodal_bridge.py", "coco_caption_sample_v1.json")
    return {**bank_code_identity(),
            **{name: sha(Path(__file__).with_name(name).read_bytes()) for name in names}}


def make_plan(*, data_sha256, bank_sha256, threads):
    return {"schema": "hepta.multimodal-research-plan.v1",
        "data_manifest_sha256": data_sha256, "bank_manifest_sha256": bank_sha256,
        "code_file_sha256": research_code_identity(), "threads": threads,
        "arms": list(ARMS), "modes": list(MODES), "primary_mode": "gated",
        "step_candidates": list(STEPS), "learning_rate": 0.2, "seed": 7,
        "adapter_rank": 4, "state_width": 8, "task_count": 2,
        "feature_transform": FUSION, "development_selection": "uncalibrated_nll_then_fewer_steps",
        "temperature_grid": list(TEMPERATURES), "temperature_selection": "calibration_nll_only",
        "test_selects_hyperparameters": False, "test_selects_reporting_winner": False,
        "interventions": list(INTERVENTIONS), "shuffle": "swap_images_within_each_pair_block",
        "shuffle_original_labels_interpretation": "sensitivity_only",
        "shuffle_relabelled_interpretation": "source_pair_consistency_same_input_multiset",
        "minority_test": {"positive_count": 32, "negative_count": 128,
            "selection": "sha256(seed:row_id)_first_32_positives_all_negatives",
            "seed": 20261022, "minimum_positive_recall": 0.60,
            "independent_replication": False, "uses_frozen_primary_model": True},
        "research_qualification": asdict(ResearchQualificationV1()),
        "quality_qualified_definition": "gated_multimodal_screen_and_minority_positive_recall",
        "head_latency": {"warmup_calls": 20, "measured_calls": 1000, "batch_size": 1},
        "budget_meaning": "same_frozen_owner_width_head_architecture_rows_steps_grid_and_threads",
        "equal_encoder_flops_claimed": False, "source_pair_mismatch_is_semantic_contradiction": False,
        "foundation_pretraining_contamination_excluded": False,
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}


def _write(path, value):
    path.write_bytes(canonical(value) + b"\n")


def _cohort(rows, bundle):
    return HeadCohortV1(bundle=bundle, labels=tuple(r["label"] for r in rows),
                        source_group_ids=tuple(r["pair_block_id"] for r in rows))


def select_head(train, calibration, development, *, mode, plan):
    """The only selection key is development raw NLL, followed by step cost."""
    candidates = []
    selected = None
    best_key = None
    for steps in plan["step_candidates"]:
        config = HeadTrainingConfigV1(task_count=2, mode=mode, steps=steps,
            learning_rate=plan["learning_rate"], seed=plan["seed"],
            adapter_rank=plan["adapter_rank"], state_width=plan["state_width"])
        began, cpu = time.perf_counter(), time.process_time()
        result = train_cell_head(train, calibration, {"development": development}, config=config)
        report = result.report
        score = report["splits"]["development"]["metrics"]["trained"]["nll"]
        candidates.append({"steps": steps, "development_uncalibrated_nll": score,
            "train_uncalibrated_nll": report["splits"]["train"]["metrics"]["trained"]["nll"],
            "wall_ms": (time.perf_counter() - began) * 1000,
            "process_cpu_ms": (time.process_time() - cpu) * 1000,
            "trained_tensor_sha256": report["trained_tensor_sha256"]})
        key = (score, steps)
        if best_key is None or key < best_key:
            selected, best_key = result, key
        print(json.dumps({"stage": "head_training", "mode": mode, **candidates[-1]}), flush=True)
    return selected, {"candidates": candidates, "selected_steps": best_key[1],
        "selection_used_test": False, "selection_used_calibration_metrics": False,
        "total_optimizer_steps_including_selection": sum(plan["step_candidates"])}


def minority_indices(rows, plan):
    spec = plan["minority_test"]
    positives = [i for i, row in enumerate(rows) if row["label"] == 1]
    negatives = [i for i, row in enumerate(rows) if row["label"] == 0]
    if len(positives) < spec["positive_count"] or len(negatives) != spec["negative_count"]:
        raise ValueError("fixed minority subset counts differ from the preregistered test")
    positives.sort(key=lambda i: sha(f'{spec["seed"]}:{rows[i]["row_id"]}'.encode()))
    return sorted(positives[:spec["positive_count"]] + negatives)


def make_ledger(head, bundle, rows, plan, *, arm, split="test", intervention="paired",
                relabel=False, indices=None):
    prediction = head.predict_task(bundle)
    logits = prediction["task_logits"]
    if indices is not None:
        rows, logits = [rows[i] for i in indices], logits[indices]
    identity = LedgerIdentityV1(encoder_sha256=head.identity.encoder_sha256,
        preprocess_sha256=head.identity.preprocess_sha256,
        head_sha256=head.report["trained_tensor_sha256"],
        data_sha256=plan["data_manifest_sha256"], plan_sha256=sha(canonical(plan)))
    return PredictionLedgerV1.from_logits(logits=logits,
        labels=np.array([1 - r["label"] if relabel else r["label"] for r in rows]),
        source_ids=[r["row_id"] for r in rows], image_group_ids=[r["group_id"] for r in rows],
        pair_block_ids=[r["pair_block_id"] for r in rows], identity=identity,
        split=split, arm=arm, intervention=intervention, temperature=prediction["temperature"])


def retain_ledger(ledger, output, key):
    saved = save_prediction_ledger(ledger, output / key)
    loaded = load_prediction_ledger(output / key,
        expected_manifest_sha256=saved["manifest_sha256"], expected_identity=ledger.identity)
    if loaded.ledger_sha256 != ledger.ledger_sha256:
        raise ValueError("saved prediction ledger failed round-trip verification")
    # The bounded NPZ contains every raw row. JSON is a convenient human-readable copy.
    _write(output / key / "rows.json", ledger.rows())
    return {**{k: v for k, v in saved.items() if k != "directory"},
            "directory": key, "metrics": ledger.metrics(), "round_trip_verified": True}


def measure_head(head, bundle, plan):
    one = FeatureBundleV1.from_tensors(global_features=bundle.read_global()[:1],
        source_record_digests=bundle.source_record_digests[:1], identity=bundle.identity,
        missing_mask=bundle.snapshot()["missing_mask"][:1])
    for _ in range(plan["head_latency"]["warmup_calls"]):
        head.predict_task(one)
    samples = []
    for _ in range(plan["head_latency"]["measured_calls"]):
        began = time.perf_counter_ns()
        head.predict_task(one)
        samples.append((time.perf_counter_ns() - began) / 1e6)
    report = head.report
    resident = sum(t.numel() * t.element_size() for t in head._head.state_dict().values())
    return {"resident_tensor_bytes": resident,
        "resident_parameters": report["resident_parameter_count"],
        "trainable_parameters": report["trainable_parameter_count"],
        "latency_ms_samples": samples, "p50_ms": float(np.quantile(samples, .5)),
        "p95_ms": float(np.quantile(samples, .95)), "p99_ms": float(np.quantile(samples, .99)),
        "includes_identity_hash_checks_and_feature_copy": True,
        "includes_encoder_or_queueing": False, "observed_target_device": False,
        "resident_tensor_bytes_for_4096_heads_arithmetic": resident * 4096,
        "4096_heads_physically_allocated_in_this_run": False}


def _environment():
    limits = {}
    for name in ("cpu.max", "memory.max"):
        path = Path("/sys/fs/cgroup") / name
        limits[name] = path.read_text().strip() if path.is_file() else None
    powercap = Path("/sys/class/powercap")
    return {"platform": platform.platform(), "torch": torch.__version__,
        "numpy": np.__version__, "cgroup": limits, "cuda_available": torch.cuda.is_available(),
        "powercap_directory_present": powercap.is_dir(),
        "energy_joules": None, "energy_measured": False,
        "target_device_qualified": False,
        "energy_reason": "no device energy measurement instrument attached to this experiment"}


def run_research(*, cohorts, bank, expected_bank_sha256, output, threads=4):
    if type(threads) is not int or not 1 <= threads <= 8:
        raise ValueError("bounded CPU thread budget required")
    target, root = Path(output), Path(cohorts)
    if target.exists() or not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("new output under an existing real parent required")
    data_sha = sha((root / "manifest.json").read_bytes())
    dataset, rows = load_cohorts(root, expected_manifest_sha256=data_sha)
    manifest, features = load_bank(bank, expected_manifest_sha256=expected_bank_sha256,
                                   expected_data_sha256=data_sha)
    plan = make_plan(data_sha256=data_sha, bank_sha256=expected_bank_sha256, threads=threads)
    target.mkdir(mode=0o700)
    _write(target / "plan.json", plan)
    _write(target / "cohort-manifest.json", dataset)
    _write(target / "bank-manifest.json", manifest)
    started_at = datetime.now(timezone.utc).isoformat()
    began = time.perf_counter()
    torch.set_num_threads(threads)
    heads, selections, test_bundles, artifacts = {}, {}, {}, {}
    # Test feature views and predictions are deliberately created after all selection.
    for arm in ARMS:
        views = {split: _cohort(rows[split], pair_features(rows[split], manifest, features, arm=arm))
                 for split in ("train", "calibration", "dev")}
        for mode in MODES:
            key = f"{arm}-{mode}"
            head, selection = select_head(views["train"], views["calibration"], views["dev"],
                                          mode=mode, plan=plan)
            saved = save_head_artifact(head, target / (key + "-head"))
            loaded = load_head_artifact(target / (key + "-head"),
                expected_manifest_sha256=saved["manifest_sha256"], expected_identity=head.identity)
            if not torch.equal(head.predict_task(views["dev"].bundle)["task_logits"],
                               loaded.predict_task(views["dev"].bundle)["task_logits"]):
                raise ValueError("reloaded Head predictions differ")
            heads[key], selections[key] = loaded, selection
            artifacts[key] = {**{k: v for k, v in saved.items() if k != "directory"},
                              "directory": key + "-head", "round_trip_verified": True}
    _write(target / "selection.json", selections)
    ledgers, ledger_records, head_costs, screens = {}, {}, {}, {}
    minor_indices = minority_indices(rows["test"], plan)
    for arm in ARMS:
        bundle = pair_features(rows["test"], manifest, features, arm=arm)
        test_bundles[arm] = bundle
        for mode in MODES:
            key = f"{arm}-{mode}"
            head = heads[key]
            ledger = make_ledger(head, bundle, rows["test"], plan, arm=key)
            ledgers[key] = ledger
            ledger_records[key] = retain_ledger(ledger, target, key + "-test")
            screens[key] = assess_research_qualification(ledger, plan)
            minority = make_ledger(head, bundle, rows["test"], plan, arm=key,
                                   split="minority_test", indices=minor_indices)
            ledgers[key + "-minority"] = minority
            ledger_records[key + "-minority"] = retain_ledger(minority, target, key + "-minority")
            ledger_records[key + "-minority"]["cluster_intervals"] = cluster_intervals(minority)
            head_costs[key] = measure_head(head, bundle, plan)
    multimodal = {}
    for mode in MODES:
        key = f"text_image-{mode}"
        changes = {}
        for intervention in INTERVENTIONS:
            bundle = pair_features(rows["test"], manifest, features,
                                   arm="text_image", intervention=intervention)
            ledger = make_ledger(heads[key], bundle, rows["test"], plan,
                                 arm=key, intervention=intervention)
            changes[intervention] = ledger
            name = key + "-" + intervention
            ledger_records[name] = retain_ledger(ledger, target, name)
            if intervention == "shuffled_image":
                relabelled = make_ledger(heads[key], bundle, rows["test"], plan,
                    arm=key, intervention="shuffled_relabelled", relabel=True)
                name = key + "-shuffled_relabelled"
                ledger_records[name] = retain_ledger(relabelled, target, name)
        multimodal[mode] = assess_multimodal_research(ledgers[key],
            unimodal={arm: ledgers[f"{arm}-{mode}"] for arm in ("text_only", "image_only")},
            interventions=changes, plan=plan)
    minority_metrics = ledgers["text_image-gated-minority"].metrics()
    minority_ok = (minority_metrics["positive_recall"] >= plan["minority_test"]["minimum_positive_recall"])
    _write(target / "head-costs.json", head_costs)
    if plan["code_file_sha256"] != research_code_identity():
        raise ValueError("source changed during preregistered research execution")
    load_cohorts(root, expected_manifest_sha256=data_sha)
    load_bank(bank, expected_manifest_sha256=expected_bank_sha256, expected_data_sha256=data_sha)
    if sha(canonical(json.loads((target / "plan.json").read_bytes()))) != sha(canonical(plan)):
        raise ValueError("preregistered plan bytes changed during execution")
    report = {"schema": "hepta.multimodal-research-report.v1", "engineering_status": "COMPLETE",
        "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": sha(canonical(plan)), "plan": plan, "environment": _environment(),
        "data_manifest_sha256": data_sha, "bank_manifest_sha256": expected_bank_sha256,
        "head_artifacts": artifacts, "selection": selections, "ledgers": ledger_records,
        "arm_screens": screens, "multimodal_screens": multimodal,
        "gated_vs_linear": {arm: paired_intervention_summary(ledgers[f"{arm}-gated"],
            ledgers[f"{arm}-linear"], comparison_kind="head") for arm in ARMS},
        "minority_primary_recall_check": minority_ok,
        "quality_qualified": multimodal["gated"]["multimodal_gain_research_screen_passed"] and minority_ok,
        "encoder_calls_during_head_training": 0, "encoder_calls_during_head_serving": 0,
        "physical_encoder_owners_in_feature_bank": 1,
        "encoder_resources": manifest["encoder"], "bank_cost": manifest["runtime"],
        "head_wall_ms_including_selection_evaluation_and_artifact_checks": (time.perf_counter() - began) * 1000,
        "head_process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "head_process_final_rss": rss_observation(),
        "state_policy_learning_qualified": False, "target_device_performance_qualified": False,
        "artifact_sha256": {str(p.relative_to(target)): sha(p.read_bytes())
                            for p in sorted(target.rglob("*")) if p.is_file()},
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}
    _write(target / "report.json", report)
    print(json.dumps({"engineering_status": "COMPLETE", "quality_qualified": report["quality_qualified"],
        "multimodal_screens": {k: v["status"] for k, v in multimodal.items()}}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cohorts", "bank", "expected-bank-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--threads", type=int, default=4)
    run_research(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
