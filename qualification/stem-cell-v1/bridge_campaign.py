"""V6 equal-parameter cross-fact experiment; no official validation is read."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import binding_panel, natural_panel
from binding_continuation import continuation_plan, continue_binding_reader
from binding_protocol import retention_gate, warmup_gate
from binding_training import fit_binding_reader
from bridge_campaign_utils import (SEEDS, VARIANTS, baseline_records, build_reader,
    checked_design, load_bank, load_model, load_verifier, old_inputs, phase_cost,
    reader_identity, save_initialization, save_model, selected_model_paths, source_inventory, typed_digest, write)
from group_encoder import file_digest
from revision_training import fit_revision_pair

CONTINUATIONS = ("natural_only", "replay", "contrastive")
ORDER = {41: ("bridge", "wide"), 47: ("wide", "bridge"), 53: ("bridge", "wide")}


def prepare(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    args.output.mkdir(parents=True, exist_ok=False)
    previous, parts, natural = old_inputs(args)
    baselines = baseline_records(args)
    initialization_files = {}
    for seed in SEEDS:
        for arm in ("base", *VARIANTS):
            folder = args.output / f"seed-{seed}" / arm
            save_initialization(folder, build_reader(arm, seed), seed)
            for name in ("initialization.json", "initialization.bin"):
                initialization_files[str((folder / name).relative_to(args.output))] = file_digest(folder / name)
    design = dict(schema="hepta.bridge.campaign.v6", runtime_source_sha256=source_inventory(),
        previous_v5_design_sha256=file_digest(args.previous_v5 / "design.json"),
        membership=previous["membership"], natural_case_ids=previous["natural_case_ids"],
        initialization_files_sha256=initialization_files, historical_baselines=baselines,
        historical_baseline_scope="three_actual_V5_runs_identical_recipe_inputs_and_common_initial_weights",
        reused_baseline_is_free_compute=False, primary_variant="bridge", control_variant="wide",
        order={str(k): list(v) for k, v in ORDER.items()},
        training=dict(max_updates=8000, batch_size=16, depth=3, learning_rate=.001,
            pair_weight=.5, diagnostic_interval=250, wall_time_budget_ns=1_800_000_000_000,
            loss="last_hop_CE_plus_world_pair_margin", stopping="earliest_full_train_gate"),
        continuation=dict(primary_only=True, updates=500, arms=list(CONTINUATIONS)),
        feedback=dict(primary_only=True, natural_updates=256, binding_updates=256, arms=["real", "zero"]),
        gate=dict(candidate_accuracy=1., paired_world_accuracy=1., maximum_probability_CE=.10,
            every_primary_seed_required=True, control_cannot_replace_failed_primary=True),
        retention=dict(candidate_accuracy=.95, paired_world_accuracy=.95, maximum_drop=.05),
        natural_internal_tune_is_hard_gate=False, natural_cross_variant_transfer_comparison=False,
        fresh_opening="primary_all_seeds_fit_then_contrastive_retention_then_all_models_frozen",
        same_parameter_count_is_same_compute=False, same_budget_limit_is_same_actual_cost=False,
        neural_phases_sequential=True, official_validation_read=False, hosted_ci_consulted=False,
        production_authorized=False, created_ns=time.time_ns())
    write(args.output, "design.json", design)
    write(args.output, "all-cases.json", {k: [asdict(c) for c in v] for k, v in parts.items()})
    write(args.output, "preparation-cost.json", phase_cost(started))


def warmup(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    _, parts, natural = checked_design(args)
    if (args.output / "warmup-completion.json").exists():
        raise ValueError("V6 warmup has already completed")
    with (args.output / "warmup-start.json").open("x") as stream:
        json.dump(dict(started_ns=time.time_ns(), retries_authorized=False), stream)
    bank = load_bank(args)
    data, gates = bank.batch(parts["reader_train"]), {}
    for seed in SEEDS:
        gates[str(seed)] = {}
        for arm in ORDER[seed]:
            folder = args.output / f"seed-{seed}" / arm
            if (folder / "warmup-training.json").exists() or (folder / "warmup-failed.json").exists():
                raise ValueError("an existing attempt cannot be overwritten or silently resumed")
            model = build_reader(arm, seed)
            initial = json.loads((folder / "initialization.json").read_text())
            if typed_digest(model) != initial["execution_parameter_sha256"]:
                raise ValueError("actual training initialization changed")
            model, receipt = fit_binding_reader(model, data, parts["reader_train"], steps=8000,
                seed=seed, batch_size=16, depth=3, learning_rate=.001, pair_weight=.5,
                diagnostic_interval=250, wall_time_ns=1_800_000_000_000,
                failure_receipt_fn=lambda r: write(folder, "warmup-failed.json", r))
            save_model(folder, "warmup", model, receipt, seed=seed,
                       initial_digest=initial["execution_parameter_sha256"])
            metrics = binding_panel(folder, "warmup-binding-train", model, parts["reader_train"], bank)
            gates[str(seed)][arm] = warmup_gate(metrics)
            write(folder, "warmup-gate.json", gates[str(seed)][arm])
            natural_panel(folder, "warmup-natural-internal", model, natural["tune"], bank)
            print(json.dumps(dict(phase="warmup", seed=seed, arm=arm, updates=receipt["completed_steps"],
                metrics=metrics, gate=gates[str(seed)][arm], architecture=reader_identity(model))), flush=True)
    write(args.output, "warmup-completion.json", dict(completed_ns=time.time_ns(), gates=gates,
        admitted={arm: all(g[arm]["passed"] for g in gates.values()) for arm in VARIANTS},
        primary_all_passed=all(g["bridge"]["passed"] for g in gates.values()),
        historical_baselines_newly_trained=False, phase_cost=phase_cost(started),
        runtime_source_sha256=source_inventory(), fresh_scoring_authorized=False))


def continuation(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    _, parts, natural = checked_design(args)
    gate = json.loads((args.output / "warmup-completion.json").read_text())
    if not gate["primary_all_passed"]:
        raise ValueError("all bridge seeds must pass before primary continuation")
    if (args.output / "continuation-completion.json").exists():
        raise ValueError("continuation has already completed")
    with (args.output / "continuation-start.json").open("x") as stream:
        json.dump(dict(started_ns=time.time_ns(), retries_authorized=False), stream)
    bank = load_bank(args)
    data, natural_data = bank.batch(parts["reader_train"]), bank.dataset(natural["train"])
    anchors = list(dict.fromkeys(c.question_key for c in natural["train"]))[:8]
    diagnostic = bank.dataset([c for c in natural["train"] if c.question_key in anchors])
    gates = {}
    for seed in SEEDS:
        folder = args.output / f"seed-{seed}" / "bridge"
        model, record = load_model(folder, "warmup", expected_arm="bridge")
        baseline = json.loads((folder / "warmup-binding-train.json").read_text())["metrics"]
        plan = continuation_plan(natural["train"], parts["reader_train"], seed=seed, updates=500)
        write(folder, "continuation-plan.json", plan)
        gates[str(seed)] = {}
        for arm in CONTINUATIONS:
            trained, receipt = continue_binding_reader(model, natural_data, data, parts["reader_train"],
                arm=arm, plan=plan, natural_diagnostic=diagnostic, natural_cases=natural["train"],
                depth=3, learning_rate=.001, diagnostic_interval=100, wall_time_ns=1_800_000_000_000,
                failure_receipt_fn=lambda r: write(folder, arm + "-failed.json", r))
            if receipt["completed_steps"] != 500:
                raise RuntimeError("incomplete fixed continuation budget")
            save_model(folder, arm, trained, receipt, seed=seed,
                       initial_digest=record["execution_parameter_sha256"])
            metrics = binding_panel(folder, arm + "-binding-train", trained, parts["reader_train"], bank)
            gates[str(seed)][arm] = retention_gate(metrics, baseline)
            binding_panel(folder, arm + "-binding-internal", trained, parts["internal_tune"], bank)
            natural_panel(folder, arm + "-natural-internal", trained, natural["tune"], bank)
            print(json.dumps(dict(phase="continuation", seed=seed, arm=arm, metrics=metrics,
                                  gate=gates[str(seed)][arm])), flush=True)
        write(folder, "retention-gates.json", gates[str(seed)])
    write(args.output, "continuation-completion.json", dict(completed_ns=time.time_ns(), gates=gates,
        contrastive_all_passed=all(g["contrastive"]["passed"] for g in gates.values()),
        phase_cost=phase_cost(started), runtime_source_sha256=source_inventory(), fresh_scoring_authorized=False))


def feedback(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    _, parts, natural = checked_design(args)
    if not json.loads((args.output / "continuation-completion.json").read_text())["contrastive_all_passed"]:
        raise ValueError("primary retention gate closed")
    if (args.output / "all-models-frozen.json").exists():
        raise ValueError("revision models have already frozen")
    with (args.output / "feedback-start.json").open("x") as stream:
        json.dump(dict(started_ns=time.time_ns(), retries_authorized=False), stream)
    bank = load_bank(args)
    data, natural_data = bank.batch(parts["reader_train"]), bank.dataset(natural["train"])
    for seed in SEEDS:
        folder = args.output / f"seed-{seed}" / "bridge"
        core, record = load_model(folder, "contrastive", expected_arm="bridge")
        verifier, provenance = load_verifier(args, seed, natural["train"], parts["reader_train"])
        plan = continuation_plan(natural["train"], parts["reader_train"], seed=seed, updates=256)
        write(folder, "revision-plan.json", plan)
        models, receipt = fit_revision_pair(core, verifier, natural_data, data, parts["reader_train"],
            plan=plan, verifier_provenance=provenance, natural_cases=natural["train"],
            learning_rate=.001, pair_weight=.5, wall_time_ns=1_800_000_000_000,
            failure_receipt_fn=lambda r: write(folder, "revision-failed.json", r))
        if receipt["completed_logical_updates"] != 256 or not receipt["feedback_training_verified"]:
            raise RuntimeError("incomplete trained feedback or unverified gradients")
        write(folder, "revision-pair-training.json", receipt)
        for arm, model in models.items():
            if reader_identity(model) != reader_identity(core):
                raise ValueError("feedback training changed architecture identity")
            save_model(folder, "revision-" + arm, model,
                dict(model_receipt=receipt["models"][arm], shared_training_receipt="revision-pair-training.json",
                     shared_receipt_sha256=file_digest(folder / "revision-pair-training.json")),
                seed=seed, initial_digest=record["execution_parameter_sha256"])
        print(json.dumps(dict(seed=seed, phase="feedback", verified=True)), flush=True)
    manifests = {str(p.relative_to(args.output)): file_digest(p)
                 for p in args.output.glob("seed-*/*/*-model.json")}
    if set(manifests) != set(selected_model_paths()):
        raise ValueError("selected model family is incomplete or contains unexpected artifacts")
    gate_files = ["warmup-completion.json", "continuation-completion.json"]
    gate_files.extend(f"seed-{s}/bridge/retention-gates.json" for s in SEEDS)
    write(args.output, "all-models-frozen.json", dict(frozen_ns=time.time_ns(), manifests=manifests,
        gate_evidence_sha256={n: file_digest(args.output / n) for n in gate_files},
        phase_cost=phase_cost(started), runtime_source_sha256=source_inventory(),
        historical_base_selection_bound_by_design=True, fresh_started=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "warmup", "continue", "feedback", "evaluate"))
    for name in ("source", "snapshot", "prepared", "previous-main", "previous-native", "previous-v5", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.phase == "evaluate":
        from bridge_evaluation import evaluate
        evaluate(args)
    else:
        {"prepare": prepare, "warmup": warmup, "continue": continuation, "feedback": feedback}[args.phase](args)


if __name__ == "__main__":
    main()
