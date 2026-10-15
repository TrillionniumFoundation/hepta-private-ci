"""V9 fixed 2×2 training over shared real Encoder features and common starts."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import binding_panel
from grounding_campaign_utils import (ARMS, ORDER, SEEDS, checked_design, historical_records,
    learning_change, load_bank, load_bridge, load_initialization, old_inputs, phase_cost,
    save_initialization, save_model, source_inventory, typed_digest, write)
from grounding_protocol import build_grounding_protocol, grounding_manifest
from grounding_reader import load_grounding_warmup
from grounding_spans import grounding_from_bank
from grounding_training import continue_grounding
from group_encoder import file_digest
from retention_campaign import natural_panel
from retention_data import joint_gate
from retention_v7_training import make_retention_plan


def prepare(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    args.output.mkdir(parents=True, exist_ok=False)
    previous, parts, natural, augmentation = old_inputs(args)
    fresh = build_grounding_protocol(parts, augmentation)
    write(args.output, "all-cases.json", {name: [asdict(c) for c in cases] for name, cases in dict(
        reader_train=parts["reader_train"], internal_tune=parts["internal_tune"], augmentation=augmentation,
        natural_train=natural["train"], natural_internal=natural["tune"], **fresh).items()})
    # Loading and authenticating an existing cache does not execute the Encoder.
    bank = load_bank(args)
    before = bank.forward_batches, bank.encoded_sequences
    targets = dict(binding=grounding_from_bank(parts["reader_train"], bank),
                   augmentation=grounding_from_bank(augmentation, bank))
    write(args.output, "auxiliary-targets.json", targets)
    models = {}
    for seed in SEEDS:
        core, _ = load_bridge(args.previous_v6/f"seed-{seed}"/"bridge", "warmup", expected_arm="bridge")
        plan = make_retention_plan(natural["train"], parts["reader_train"], augmentation, seed=seed)
        if plan != json.loads((args.previous_v7/f"seed-{seed}"/"training-plan.json").read_text()):
            raise ValueError("V9 must use exactly the actual V7/V8 sample sequence")
        write(args.output, f"seed-{seed}/training-plan.json", plan)
        for arm in ARMS:
            model = load_grounding_warmup(core, arm, seed=seed)
            save_initialization(args.output/f"seed-{seed}"/arm, model, core, seed)
            models[(seed, arm)] = model
    patterns = ("all-cases.json", "auxiliary-targets.json", "seed-*/training-plan.json",
        "seed-*/*/initialization.json", "seed-*/*/initialization.pt", "seed-*/*/initialization.bin")
    prepared = {str(p.relative_to(args.output)): file_digest(p) for pattern in patterns for p in args.output.glob(pattern)}
    design = dict(schema="hepta.grounding.campaign.v9", created_ns=time.time_ns(),
        runtime_source_sha256=source_inventory(), protocol_sha256=file_digest(Path(__file__).parent/"GROUNDING_V9_PROTOCOL.md"),
        previous_v8_design_sha256=file_digest(args.previous_v8/"design.json"),
        previous_v8_completion_sha256=file_digest(args.previous_v8/"training-completion.json"),
        reused_cache_files_sha256=previous["extended_cache_files_sha256"], historical=historical_records(args, previous),
        prepared_files_sha256=prepared, primary="grounded_chain", arms=list(ARMS),
        order={str(s): list(v) for s, v in ORDER.items()},
        factors=dict(grounded="training_only_span_and_cross_context_entity_losses", chain="carry_graph_address_across_two_hops"),
        training=dict(logical_updates=500, streams=["natural", "transfer", "retention"], batch_size=16,
            legacy_depth=3, graph_depth=2, learning_rate=.001, pair_weight=.5, span_weight=1.,
            contrastive_weight=.1, contrastive_temperature=.1, diagnostic_interval=100,
            optimizer_updates_per_model=1500, candidate_exposures_per_model=24000,
            stop_rule="fixed_final_no_selection", teacher_calls=0, teacher_distillation=False),
        fresh=grounding_manifest(fresh, parts, augmentation), natural_constants=previous["natural_constants"],
        old_gates=previous["gates"], feedback_authorized=False, fresh_authorized=True,
        fresh_requires_all_twelve_frozen=True, fresh_independent_of_old_qualification=True,
        original_V5_fresh_authorized=False, official_validation_read=False,
        initial_actual_candidate_observations=1536, hosted_ci_consulted=False, production_authorized=False)
    # Complete protocol, data, train-only spans, plans and starts freeze before predictions.
    write(args.output, "design.json", design)
    panels, equality = {}, {}
    for seed in SEEDS:
        reference = None
        warmup = json.loads((args.previous_v6/f"seed-{seed}"/"bridge"/"warmup-binding-train.json").read_text())
        if warmup["case_ids"] != [c.case_id for c in parts["reader_train"]]:
            raise ValueError("actual historical warmup observations have different rows")
        for arm in ARMS:
            folder = args.output/f"seed-{seed}"/arm
            binding_panel(folder, "initial-binding-train", models[(seed, arm)], parts["reader_train"], bank)
            panel = json.loads((folder/"initial-binding-train.json").read_text())
            if (panel["probabilities"] != warmup["probabilities"]
                    or reference is not None and panel["probabilities"] != reference):
                raise ValueError("zero graph output changed actual four-arm initial probabilities")
            reference = panel["probabilities"]
            panels[str((folder/"initial-binding-train.json").relative_to(args.output))] = file_digest(folder/"initial-binding-train.json")
        equality[str(seed)] = True
    if before != (bank.forward_batches, bank.encoded_sequences) or source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("V9 preparation unexpectedly encoded inputs or changed runtime")
    write(args.output, "preparation-completion.json", dict(design_sha256=file_digest(args.output/"design.json"),
        completed_ns=time.time_ns(), initial_panels_sha256=panels, exact_initial_probability_equality=equality,
        actual_initial_candidate_observations=1536, new_encoder_forward_batches=0,
        reused_encoder_report=bank.report(), phase_cost=phase_cost(started)))


def train(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    design, parts, natural, augmentation = checked_design(args)
    with (args.output/"training-start.json").open("x") as f:
        json.dump(dict(started_ns=time.time_ns(), retries_authorized=False), f)
    bank = load_bank(args)
    before = bank.forward_batches, bank.encoded_sequences
    old_data, new_data, natural_data = (bank.dataset(cases) for cases in
        (parts["reader_train"], augmentation, natural["train"]))
    targets = json.loads((args.output/"auxiliary-targets.json").read_text())
    gates = {}
    for seed in SEEDS:
        seed_folder = args.output/f"seed-{seed}"
        historical = args.previous_v6/f"seed-{seed}"/"bridge"
        baseline = json.loads((historical/"warmup-binding-train.json").read_text())["metrics"]
        start = json.loads((args.previous_v7/f"seed-{seed}"/"start-natural-train.json").read_text())["metrics"]
        plan = json.loads((seed_folder/"training-plan.json").read_text())
        gates[str(seed)] = {}
        for arm in ORDER[seed]:
            folder = seed_folder/arm
            model, initial = load_initialization(folder)
            trained, receipt = continue_grounding(model, natural_data, old_data, new_data, parts["reader_train"],
                augmentation, plan=plan, natural_cases=natural["train"], grounding_targets=targets, arm=arm,
                depth=3, graph_depth=2, diagnostic_interval=100, wall_time_ns=1_800_000_000_000,
                failure_receipt_fn=lambda r: write(folder, "final-failed.json", r))
            if receipt["status"] != "completed" or receipt["completed_steps"] != 500:
                raise RuntimeError("incomplete fixed V9 training budget")
            save_model(folder, trained, receipt, seed=seed, initial_digest=initial["execution_parameter_sha256"])
            learning_change(folder, trained)
            qualification_started = time.perf_counter_ns(), time.process_time_ns()
            old = binding_panel(folder, "final-binding-train", trained, parts["reader_train"], bank)
            relation = binding_panel(folder, "final-binding-internal", trained, parts["internal_tune"], bank)
            binding_panel(folder, "final-augmentation-train", trained, augmentation, bank)
            learned = natural_panel(folder, "final-natural-train", trained, natural["train"], bank,
                scope="complete_natural_training_partition")
            natural_panel(folder, "final-natural-internal", trained, natural["tune"], bank,
                scope="previously_exposed_descriptive_not_fresh")
            gate = joint_gate(old, baseline, relation, learned, start, design["natural_constants"])
            write(folder, "final-legacy-gate.json", gate)
            write(folder, "qualification-cost.json", phase_cost(qualification_started))
            gates[str(seed)][arm] = gate
            print(json.dumps(dict(seed=seed, arm=arm, phase="training", legacy_gate=gate)), flush=True)
    if before != (bank.forward_batches, bank.encoded_sequences) or source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("V9 training unexpectedly encoded new inputs or changed runtime")
    manifests = {str(p.relative_to(args.output)): file_digest(p) for p in args.output.glob("seed-*/*/final-model.json")}
    if len(manifests) != 12:
        raise ValueError("all twelve final weight selections must exist")
    write(args.output, "all-models-frozen.json", dict(frozen_ns=time.time_ns(), manifests=manifests,
        runtime_source_sha256=source_inventory(), feedback_authorized=False, fresh_started=False))
    write(args.output, "training-completion.json", dict(completed_ns=time.time_ns(), legacy_gates=gates,
        legacy_primary_all_passed=all(g["grounded_chain"]["passed"] for g in gates.values()),
        runtime_source_sha256=source_inventory(), phase_cost=phase_cost(started),
        new_encoder_forward_batches=0, new_teacher_forward_calls=0, actual_optimizer_updates=18000,
        actual_training_exposures=288000, feedback_authorized=False, fresh_authorized=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "train", "evaluate"))
    for name in ("source", "snapshot", "prepared", "previous-main", "previous-native", "previous-v5",
                 "previous-v6", "previous-v7", "previous-v8", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.phase == "evaluate":
        from grounding_evaluation import evaluate
        evaluate(args)
    else:
        {"prepare": prepare, "train": train}[args.phase](args)


if __name__ == "__main__":
    main()
