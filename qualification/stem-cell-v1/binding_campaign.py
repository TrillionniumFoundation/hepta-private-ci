"""V5 full binding fit, matched continuation, then trained-feedback research.

No official validation file is read. Fresh generated domains stay unscored
until every selected artifact is frozen and the main training gates pass.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import (SEEDS, binding_panel, checked_design, inputs,
    load_bank, load_model, load_verifier, natural_panel, phase_cost, save_model,
    source_inventory, typed_digest, write)
from binding_continuation import continuation_plan, continue_binding_reader
from binding_protocol import binding_manifest, retention_gate, warmup_gate
from binding_training import fit_binding_reader
from group_encoder import file_digest, digest_json
from revision_training import fit_revision_pair
from token_reader import TokenReader


ARMS = ("natural_only", "replay", "contrastive")


def prepare(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    args.output.mkdir(parents=True, exist_ok=False)
    parts, natural, dataset_sha = inputs(args)
    inventory = source_inventory()
    membership = binding_manifest(parts, dataset_files_sha256={"train.jsonl": dataset_sha},
        source_files_sha256={"v4-design": file_digest(args.previous_main / "design.json")},
        code_files_sha256=inventory)
    design = dict(schema="hepta.binding-learning-campaign.v5", membership=membership,
        runtime_source_sha256=inventory, train_file_sha256=dataset_sha, seeds=list(SEEDS),
        prepared_cache_files_sha256={name: file_digest(args.prepared / "features" / name)
                                    for name in ("metadata.json", "tokens.pt")},
        snapshot_material_sha256=file_digest(args.snapshot / "material.json"),
        previous_native_freeze_sha256=file_digest(args.previous_native / "all-artifacts-frozen.json"),
        natural_case_ids={k: [c.case_id for c in v] for k, v in natural.items()},
        natural_sources={k: sorted({c.source_hash for c in v}) for k, v in natural.items()},
        warmup=dict(max_updates=8000, diagnostic_interval=250, batch_size=16, learning_rate=.001,
                    depth=3, pair_weight=.5, evidence_weight=0., wall_time_budget_ns=1_800_000_000_000,
                    loss="last_hop_CE_plus_world_pair_margin"),
        continuation=dict(natural_updates=500, replay_updates=500, arms=list(ARMS), depth=3,
                          pair_weights=dict(natural_only=0., replay=0., contrastive=.5)),
        feedback=dict(natural_updates=256, binding_updates=256, arms=["real", "zero"],
                      depth=3, verifier="original_V4_source_disjoint_frozen_natural_only"),
        fresh_opening="all_seed_warmups_and_contrastive_retention_pass_then_all_models_frozen",
        natural_internal_tune_is_hard_gate=False,
        official_validation_loaded=False, fresh_model_selection=False, equal_actual_compute=False,
        production_authorized=False, hosted_ci_consulted=False, created_ns=time.time_ns())
    write(args.output, "design.json", design)
    write(args.output, "all-cases.json", {k: [asdict(c) for c in v] for k, v in parts.items()})
    write(args.output, "preparation-cost.json", phase_cost(started))


def warmup(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    design, parts, natural = checked_design(args)
    if (args.output / "warmup-completion.json").exists():
        raise ValueError("warmup has already completed")
    bank = load_bank(args)
    data = bank.batch(parts["reader_train"])
    gates = {}
    for seed in SEEDS:
        folder = args.output / f"seed-{seed}"
        folder.mkdir(exist_ok=False)
        torch.manual_seed(seed)
        model, receipt = fit_binding_reader(TokenReader(384, 32), data, parts["reader_train"],
            steps=8000, seed=seed, batch_size=16, depth=3, learning_rate=.001, pair_weight=.5,
            diagnostic_interval=250, wall_time_ns=1_800_000_000_000,
            failure_receipt_fn=lambda r: write(folder, "warmup-failed.json", r))
        save_model(folder, "warmup", model, receipt)
        metrics = binding_panel(folder, "warmup-binding-train", model, parts["reader_train"], bank)
        gates[str(seed)] = warmup_gate(metrics)
        write(folder, "warmup-gate.json", gates[str(seed)])
        natural_panel(folder, "warmup-natural-internal", model, natural["tune"], bank)
        print(json.dumps(dict(seed=seed, phase="warmup", updates=receipt["completed_steps"],
                             gate=gates[str(seed)], metrics=metrics)), flush=True)
    write(args.output, "warmup-completion.json", dict(completed_ns=time.time_ns(), gates=gates,
        all_passed=all(g["passed"] for g in gates.values()), fresh_scoring_authorized=False,
        phase_cost=phase_cost(started), runtime_source_sha256=source_inventory()))


def continuation(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    _, parts, natural = checked_design(args)
    warmups = json.loads((args.output / "warmup-completion.json").read_text())
    if not warmups["all_passed"]:
        raise ValueError("all full128 warmups must pass before natural continuation")
    if (args.output / "continuation-completion.json").exists():
        raise ValueError("continuation has already completed")
    bank = load_bank(args)
    data, natural_data = bank.batch(parts["reader_train"]), bank.dataset(natural["train"])
    anchors = list(dict.fromkeys(c.question_key for c in natural["train"]))[:8]
    diagnostic = bank.dataset([c for c in natural["train"] if c.question_key in anchors])
    gates = {}
    for seed in SEEDS:
        folder = args.output / f"seed-{seed}"
        model, record = load_model(folder, "warmup")
        baseline = json.loads((folder / "warmup-binding-train.json").read_text())["metrics"]
        plan = continuation_plan(natural["train"], parts["reader_train"], seed=seed, updates=500)
        write(folder, "continuation-plan.json", plan)
        seed_gates = {}
        for arm in ARMS:
            trained, receipt = continue_binding_reader(model, natural_data, data, parts["reader_train"],
                arm=arm, plan=plan, natural_diagnostic=diagnostic, depth=3, learning_rate=.001,
                diagnostic_interval=100, natural_cases=natural["train"], wall_time_ns=1_800_000_000_000,
                failure_receipt_fn=lambda r: write(folder, arm + "-failed.json", r))
            if receipt["completed_steps"] != 500:
                raise RuntimeError("incomplete fixed continuation budget")
            save_model(folder, arm, trained, receipt, initial_digest=record["execution_parameter_sha256"])
            metrics = binding_panel(folder, arm + "-binding-train", trained, parts["reader_train"], bank)
            seed_gates[arm] = retention_gate(metrics, baseline)
            binding_panel(folder, arm + "-binding-internal", trained, parts["internal_tune"], bank)
            natural_panel(folder, arm + "-natural-internal", trained, natural["tune"], bank)
            print(json.dumps(dict(seed=seed, phase="continuation", arm=arm,
                                  gate=seed_gates[arm], metrics=metrics)), flush=True)
        gates[str(seed)] = seed_gates
        write(folder, "retention-gates.json", seed_gates)
    write(args.output, "continuation-completion.json", dict(completed_ns=time.time_ns(), gates=gates,
        contrastive_all_passed=all(g["contrastive"]["passed"] for g in gates.values()),
        fresh_scoring_authorized=False, phase_cost=phase_cost(started), runtime_source_sha256=source_inventory()))


def feedback(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    _, parts, natural = checked_design(args)
    retained = json.loads((args.output / "continuation-completion.json").read_text())
    if not retained["contrastive_all_passed"]:
        raise ValueError("main Core retention gate closed; feedback cannot replace Core learning")
    if (args.output / "all-models-frozen.json").exists():
        raise ValueError("feedback models have already frozen")
    bank = load_bank(args)
    data, natural_data = bank.batch(parts["reader_train"]), bank.dataset(natural["train"])
    manifests = {}
    for seed in SEEDS:
        folder = args.output / f"seed-{seed}"
        core, record = load_model(folder, "contrastive")
        verifier, provenance = load_verifier(args, seed, natural["train"], parts["reader_train"])
        plan = continuation_plan(natural["train"], parts["reader_train"], seed=seed, updates=256)
        write(folder, "revision-plan.json", plan)
        models, receipt = fit_revision_pair(core, verifier, natural_data, data, parts["reader_train"],
            plan=plan, verifier_provenance=provenance, learning_rate=.001, pair_weight=.5,
            natural_cases=natural["train"], wall_time_ns=1_800_000_000_000,
            failure_receipt_fn=lambda r: write(folder, "revision-failed.json", r))
        if receipt["completed_logical_updates"] != 256 or not receipt["feedback_training_verified"]:
            raise RuntimeError("incomplete actual feedback training")
        write(folder, "revision-pair-training.json", receipt)
        for arm, model in models.items():
            save_model(folder, "revision-" + arm, model,
                dict(model_receipt=receipt["models"][arm], shared_training_receipt="revision-pair-training.json",
                     shared_receipt_sha256=file_digest(folder / "revision-pair-training.json")),
                initial_digest=record["execution_parameter_sha256"])
            binding_panel(folder, "revision-" + arm + "-core-without-feedback-binding-train",
                          model, parts["reader_train"], bank)
            natural_panel(folder, "revision-" + arm + "-core-without-feedback-natural-internal",
                          model, natural["tune"], bank)
        manifests[str(seed)] = {name: file_digest(folder / (name + "-model.json"))
            for name in ("warmup", *ARMS, "revision-real", "revision-zero")}
        print(json.dumps(dict(seed=seed, phase="feedback", verified=True)), flush=True)
    gate_files = ["warmup-completion.json", "continuation-completion.json"]
    gate_files.extend(f"seed-{seed}/{name}.json" for seed in SEEDS
                      for name in ("warmup-gate", "retention-gates"))
    write(args.output, "all-models-frozen.json", dict(frozen_ns=time.time_ns(), manifests=manifests,
        gate_evidence_sha256={name: file_digest(args.output / name) for name in gate_files},
        phase_cost=phase_cost(started), runtime_source_sha256=source_inventory(),
        feedback_training_budget_frozen_before_fresh=True, fresh_evaluation_started=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "warmup", "continue", "feedback", "evaluate"))
    for name in ("source", "snapshot", "prepared", "previous-main", "previous-native", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.phase == "evaluate":
        from binding_evaluation import evaluate
        evaluate(args)
    else:
        {"prepare": prepare, "warmup": warmup, "continue": continuation, "feedback": feedback}[args.phase](args)


if __name__ == "__main__":
    main()
