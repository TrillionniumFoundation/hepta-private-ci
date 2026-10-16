"""Run V7 conflict-aware continuation on ORIGINAL pinned V6 Granite token data.

Research-only add-on: does not modify V6 warmup/selected weights, CURRENT,
Neuron V1, native NDU, production routing or authority. No heldout labels are
opened, and no passed TRAIN gate by itself permits promotion or fresh scoring.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import time
from types import SimpleNamespace

import torch

from binding_continuation import continuation_plan
from binding_protocol import retention_gate
from bridge_campaign_utils import (SEEDS, checked_design, load_bank, load_model,
                                   save_model, source_inventory, write)
from binding_campaign_utils import binding_panel, natural_panel
from bridge_gradient_guard import ARMS, OLD_TASK, NEW_TASK, continue_candidate
from group_encoder import file_digest

SCHEMA = "hepta.bridge.gradient-campaign.v7.1"


def run(args):
    """Original train-only physical candidate training, old/new matched schedules."""
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("candidate output must be new; no resume or rewrite")
    previous = SimpleNamespace(source=args.source, snapshot=args.snapshot,
        prepared=args.prepared, previous_main=args.previous_main,
        previous_native=args.previous_native, previous_v5=args.previous_v5,
        output=args.previous_v6)
    design, parts, natural = checked_design(previous)
    warmup_path = args.previous_v6 / "warmup-completion.json"
    warmup = json.loads(warmup_path.read_text())
    if (warmup.get("primary_all_passed") is not True or
        warmup.get("runtime_source_sha256") != source_inventory() or
        warmup.get("fresh_scoring_authorized") is not False or
        (args.previous_v6 / "evaluation-start.json").exists()):
        raise ValueError("original V6 primary train gate/source/fresh-state required")
    bank = load_bank(previous)
    binding = bank.batch(parts["reader_train"])
    natural_train = bank.dataset(natural["train"])
    if set(binding.source_groups) & set(natural_train.source_groups):
        raise ValueError("binding/natural TRAIN sources must be disjoint")
    # No calibration/heldout/natural TEST is opened before all candidate runs.
    # These are the exact original V6 TRAIN groups, not replayed labels as fixtures.
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output, "start.json", dict(schema=SCHEMA, start_ns=time.time_ns(),
        previous_v6_design_sha256=file_digest(args.previous_v6 / "design.json"),
        previous_warmup_sha256=file_digest(warmup_path),
        original_runtime_sha256=source_inventory(),
        candidate_guard_source_sha256=file_digest(Path(__file__).with_name("bridge_gradient_guard.py")),
        candidate_campaign_source_sha256=file_digest(Path(__file__)),
        original_source_validation_scope="original_V6_checked_design_and_cached_features",
        original_pretrained_snapshots_independently_authenticated=False,
        task_roles={"old": OLD_TASK, "new": NEW_TASK},
        source_training_only=True, official_validation_unopened=True,
        final_use_authorized=False, production_authorized=False))
    results = {}
    for seed in SEEDS:
        old_folder = args.previous_v6 / f"seed-{seed}" / "bridge"
        parent, manifest = load_model(old_folder, "warmup", expected_arm="bridge")
        if (not warmup["gates"][str(seed)]["bridge"]["passed"] or
                manifest["seed"] != seed):
            raise ValueError("all frozen original V6 primary warmups must be qualified")
        original_baseline_path = old_folder / "warmup-binding-train.json"
        baseline = json.loads(original_baseline_path.read_text())["metrics"]
        plan = continuation_plan(natural["train"], parts["reader_train"], seed=seed, updates=500)
        prior_plan_path = old_folder / "continuation-plan.json"
        if (prior_plan_path.exists() and
                json.loads(prior_plan_path.read_text()) != plan):
            raise ValueError("original V6 schedule changed")
        write(args.output / f"seed-{seed}", "plan.json", plan)
        for arm in ARMS:
            folder = args.output / f"seed-{seed}" / arm
            folder.mkdir(parents=True, exist_ok=False)
            # A candidate attempt is write-once, success and failure both terminal.
            write(folder, "attempt.json", dict(schema=SCHEMA, arm=arm, seed=seed,
                original_warmup_sha256=file_digest(old_folder / "warmup-model.json"),
                original_baseline_sha256=file_digest(original_baseline_path),
                plan_sha256=plan["plan_sha256"], production_authorized=False))
            try:
                candidate, receipt = continue_candidate(parent, natural_train, binding,
                    parts["reader_train"], arm=arm, plan=plan,
                    original_natural_cases=natural["train"])
                if (receipt["attempted_optimizer_steps"] != 500 or
                        receipt["accepted_optimizer_steps"] + receipt["rejected_optimizer_steps"] != 500 or
                        receipt["actual_reader_forwards"] != 1500 or
                        receipt["actual_backward_calls"] != 1000 or
                        receipt["old_task"] != OLD_TASK or receipt["new_task"] != NEW_TASK):
                    raise RuntimeError("candidate full train work was incomplete")
                save_model(folder, "candidate", candidate, receipt, seed=seed,
                           initial_digest=manifest["execution_parameter_sha256"])
                metrics = binding_panel(folder, "old-binding-train", candidate,
                                        parts["reader_train"], bank)
                retained = retention_gate(metrics, baseline)
                natural_metrics = natural_panel(folder, "new-natural-internal-tune", candidate,
                                               natural["tune"], bank)
                write(folder, "descriptive.json", dict(arm=arm, seed=seed,
                    old_training_retention=retained, new_internal_tune=natural_metrics,
                    old_task_future_retention_verified=False,
                    complete_compute_equal=False, independent_new_task_verified=False,
                    model_selected=False, production_authorized=False))
                results[f"{seed}/{arm}"] = dict(retained_train_only=retained["passed"],
                    model_sha256=receipt["final_model_sha256"],
                    accepted_optimizer_steps=receipt["accepted_optimizer_steps"],
                    rejected_optimizer_steps=receipt["rejected_optimizer_steps"],
                    actual_cpu_ns=receipt["cpu_ns"], actual_wall_ns=receipt["wall_ns"],
                    old_train_rows=receipt["old_train_rows"],
                    new_train_rows=receipt["new_train_rows"])
            except BaseException as exc:
                write(folder, "failed.json", dict(status="failed", error_type=type(exc).__name__,
                    error=str(exc)[:512], no_model_selection=True,
                    partial_work_possible=True, production_authorized=False))
                raise
    write(args.output, "completed.json", dict(schema=SCHEMA, complete=True,
        original_v6_warmup_unchanged=True, results=results,
        cpu_ns=time.process_time_ns()-start_cpu,
        wall_ns=time.perf_counter_ns()-start_wall,
        result_status="DESCRIPTIVE_TRAIN_ONLY", source_disjoint_future_windows=0,
        task_roles={"old": OLD_TASK, "new": NEW_TASK},
        original_source_validation_scope="original_V6_checked_design_and_cached_features",
        old_task_future_retention_verified=False, generalization_verified=False,
        original_v6_scientific_gate_superseded=False,
        cell_split_authorized=False, model_selected=False, native_ndu_admitted=False,
        production_authorized=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "snapshot", "prepared", "previous-main", "previous-native",
                 "previous-v5", "previous-v6", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    run(args)


if __name__ == "__main__":
    main()
