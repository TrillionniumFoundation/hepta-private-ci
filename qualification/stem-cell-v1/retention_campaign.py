"""V7 fixed-budget relation diversity and teacher-anchor experiment."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import binding_panel
from bridge_campaign_utils import load_bank as old_bank
from group_encoder import file_digest
from reader_features import tensor_digest
from retention_campaign_utils import (ARMS, ORDER, SEEDS, checked_design, freeze_models,
    historical_models, load_bank, load_model, load_verifier, old_inputs, phase_cost,
    save_model, source_inventory, typed_digest, write)
from retention_data import joint_gate, natural_baselines, natural_metrics
from retention_feedback import feedback_panel
from retention_v7_training import continue_retention, make_retention_plan
from revision_training import fit_revision_pair
from token_campaign_utils import infer
from token_reader_training import parameter_digest


def natural_panel(root, name, model, cases, bank, *, scope):
    probabilities, batches = infer(model, cases, bank, depth=3, batch_size=16, prefix=name)
    metrics = natural_metrics(cases, probabilities)
    write(root, name + ".json", dict(metrics=metrics, probabilities=probabilities,
        batches=batches, case_ids=[c.case_id for c in cases], scope=scope,
        model_execution_parameter_sha256=typed_digest(model), threshold_selected=False,
        labels_entered_model=False))
    return metrics


def prepare(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    args.output.mkdir(parents=True, exist_ok=False)
    previous, parts, natural, augmentation, report = old_inputs(args)
    history = historical_models(args)
    bank = old_bank(args)
    before = dict(cpu_ns=bank.cpu_ns, wall_ns=bank.wall_ns,
                  batches=bank.forward_batches, sequences=bank.encoded_sequences)
    bank.register(augmentation)
    bank.save_local(args.output / "features")
    design = dict(schema="hepta.retention.campaign.v7", created_ns=time.time_ns(),
        runtime_source_sha256=source_inventory(),
        protocol_sha256=file_digest(Path(__file__).parent / "RETENTION_V7_PROTOCOL.md"),
        previous_v6_design_sha256=file_digest(args.previous_v6 / "design.json"),
        previous_v6_warmup_completion_sha256=file_digest(args.previous_v6 / "warmup-completion.json"),
        historical_warmups=history, augmentation=report,
        natural_case_ids=previous["natural_case_ids"], primary="anchored", arms=list(ARMS),
        order={str(k): list(v) for k, v in ORDER.items()},
        training=dict(logical_updates=500, streams=["natural", "transfer", "retention"],
            batch_size=16, depth=3, learning_rate=.001, low_learning_rate=.0001,
            pair_weight=.5, anchor_weight=1., diagnostic_interval=100,
            wall_time_ns=1_800_000_000_000, stop_rule="fixed_final_no_selection",
            transfer_repeat="old_binding", transfer_other="augmentation",
            anchor_stream="retention_only", teacher="frozen_V6_warmup_centered_logits"),
        extended_cache_files_sha256={n: file_digest(args.output / "features" / n)
                                    for n in ("metadata.json", "tokens.pt")},
        natural_constants=natural_baselines(natural["train"]),
        gates=dict(retention_candidate=.95, retention_pairs=.95, maximum_retention_drop=.05,
            internal_relation_candidate=.75, internal_relation_pairs=.50,
            natural_F1m_gain_over_best_constant=.05, natural_F1a_gain_over_start=.05,
            natural_EM=.05, natural_CE_ratio_to_prior=.95, every_primary_seed_required=True),
        feedback=dict(updates=256, arms=["real", "zero"], primary="real",
            original_independent_frozen_verifier=True, joint_gate_required_after_feedback=True),
        fresh_requires="all_primary_joint_gates_then_feedback_real_joint_gates_then_all_models_frozen",
        old_internal_is_unseen_generalization=False, teacher_inference_at_serving=False,
        new_parameters=0, same_parameter_count_is_same_compute=False,
        equal_exposures_is_equal_compute=False, official_validation_read=False,
        hosted_ci_consulted=False, production_authorized=False)
    write(args.output, "design.json", design)
    write(args.output, "all-cases.json", {k: [asdict(c) for c in v]
        for k, v in {**parts, "augmentation": augmentation}.items()})
    write(args.output, "augmentation-encoder.json", dict(report=bank.report(),
        incremental_encoding={k: getattr(bank, attr) - before[k] for k, attr in (
            ("cpu_ns", "cpu_ns"), ("wall_ns", "wall_ns"),
            ("batches", "forward_batches"), ("sequences", "encoded_sequences"))},
        historical_cache_generation_not_additive=True))
    write(args.output, "preparation-cost.json", phase_cost(started))


def teacher_cache(folder, model, record, cases, data, design):
    """Execute the immutable teacher once per seed; other arms reuse raw FP32 logits."""
    started = time.perf_counter_ns(), time.process_time_ns()
    logits, batches = [], []
    with torch.no_grad():
        for start in range(0, len(cases), 16):
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            indices = list(range(start, min(start + 16, len(cases))))
            value = model(*data.take(indices).features(), steps=3)
            logits.append(value.detach().clone())
            batches.append(dict(case_ids=[cases[i].case_id for i in indices],
                cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-wall))
    values = torch.cat(logits)
    if values.shape != (len(cases), 2) or values.dtype != torch.float32 or not torch.isfinite(values).all():
        raise ValueError("finite FP32 old-task teacher logits required")
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "teacher-logits.bin").write_bytes(values.numpy().tobytes())
    write(folder, "teacher.json", dict(schema="hepta.retention.teacher.v7", logits=values.tolist(),
        raw_logits_sha256=tensor_digest(values), dtype=str(values.dtype), shape=list(values.shape),
        raw_file="teacher-logits.bin", raw_file_sha256=file_digest(folder / "teacher-logits.bin"),
        raw_tensor_bytes=values.numel()*values.element_size(), case_ids=[c.case_id for c in cases],
        public_source_sha256=[c.feature_source_hash for c in cases], batches=batches,
        model_execution_parameter_sha256=typed_digest(model), model_training_parameter_sha256=parameter_digest(model),
        warmup_weight_file_sha256=record["file_sha256"],
        feature_cache_files_sha256=design["extended_cache_files_sha256"],
        teacher_frozen=True, labels_entered_model=False, inference_feature_arguments=6,
        used_by="anchored_retention_loss_only", common_preparation_not_recharged_per_arm=True,
        phase_cost=phase_cost(started)))
    return values


def qualify(folder, name, model, parts, natural, augmentation, bank, baseline, start, constants):
    old = binding_panel(folder, name + "-binding-train", model, parts["reader_train"], bank)
    relation = binding_panel(folder, name + "-binding-internal", model, parts["internal_tune"], bank)
    binding_panel(folder, name + "-augmentation-train", model, augmentation, bank)
    learned = natural_panel(folder, name + "-natural-train", model, natural["train"], bank,
                            scope="complete_natural_training_partition")
    natural_panel(folder, name + "-natural-internal", model, natural["tune"], bank,
                  scope="previously_exposed_training_source_internal_tune_not_fresh")
    gate = joint_gate(old, baseline, relation, learned, start, constants)
    write(folder, name + "-gate.json", gate)
    return gate


def train(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    design, parts, natural, augmentation = checked_design(args)
    with (args.output / "training-start.json").open("x") as stream:
        json.dump(dict(started_ns=time.time_ns(), retries_authorized=False), stream)
    bank = load_bank(args)
    old_data, new_data = bank.dataset(parts["reader_train"]), bank.dataset(augmentation)
    natural_data, gates = bank.dataset(natural["train"]), {}
    for seed in SEEDS:
        historical = args.previous_v6 / f"seed-{seed}" / "bridge"
        model, record = load_model(historical, "warmup", expected_arm="bridge")
        folder = args.output / f"seed-{seed}"
        teacher = teacher_cache(folder, model, record, parts["reader_train"], old_data, design)
        start = natural_panel(folder, "start-natural-train", model, natural["train"], bank,
                              scope="complete_natural_training_partition_before_updates")
        baseline = json.loads((historical / "warmup-binding-train.json").read_text())["metrics"]
        plan = make_retention_plan(natural["train"], parts["reader_train"], augmentation, seed=seed)
        write(folder, "training-plan.json", plan)
        gates[str(seed)] = {}
        for arm in ORDER[seed]:
            trained, receipt = continue_retention(model, natural_data, old_data, new_data,
                parts["reader_train"], augmentation, arm=arm, plan=plan,
                teacher_logits=teacher, teacher_logits_sha256=tensor_digest(teacher),
                natural_cases=natural["train"], depth=3, diagnostic_interval=100,
                wall_time_ns=1_800_000_000_000,
                failure_receipt_fn=lambda r: write(folder, arm + "-failed.json", r))
            if receipt["completed_steps"] != 500 or receipt["status"] != "completed":
                raise RuntimeError("incomplete fixed V7 training budget")
            save_model(folder, arm, trained, receipt, seed=seed,
                       initial_digest=record["execution_parameter_sha256"])
            gates[str(seed)][arm] = qualify(folder, arm, trained, parts, natural, augmentation,
                bank, baseline, start, design["natural_constants"])
            print(json.dumps(dict(seed=seed, arm=arm, phase="training", gate=gates[str(seed)][arm])), flush=True)
    if source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("runtime changed during V7 training")
    write(args.output, "training-completion.json", dict(completed_ns=time.time_ns(), gates=gates,
        primary_all_passed=all(g["anchored"]["passed"] for g in gates.values()),
        phase_cost=phase_cost(started), runtime_source_sha256=source_inventory(), fresh_scoring_authorized=False))


def feedback(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    design, parts, natural, augmentation = checked_design(args)
    if not json.loads((args.output / "training-completion.json").read_text())["primary_all_passed"]:
        raise ValueError("V7 joint qualification closed")
    with (args.output / "feedback-start.json").open("x") as stream:
        json.dump(dict(started_ns=time.time_ns(), retries_authorized=False), stream)
    bank, gates = load_bank(args), {}
    for seed in SEEDS:
        folder = args.output / f"seed-{seed}"
        core, record = load_model(folder, "anchored", expected_arm="bridge")
        verifier, provenance = load_verifier(args, seed, natural["train"], parts["reader_train"])
        from binding_continuation import continuation_plan
        plan = continuation_plan(natural["train"], parts["reader_train"], seed=seed, updates=256)
        write(folder, "revision-plan.json", plan)
        models, receipt = fit_revision_pair(core, verifier, bank.dataset(natural["train"]),
            bank.dataset(parts["reader_train"]), parts["reader_train"], plan=plan,
            verifier_provenance=provenance, natural_cases=natural["train"],
            learning_rate=.001, pair_weight=.5, wall_time_ns=1_800_000_000_000,
            failure_receipt_fn=lambda r: write(folder, "revision-failed.json", r))
        if receipt["completed_logical_updates"] != 256 or not receipt["feedback_training_verified"]:
            raise RuntimeError("incomplete actual on-policy feedback training")
        write(folder, "revision-pair-training.json", receipt)
        historical = args.previous_v6 / f"seed-{seed}" / "bridge"
        baseline = json.loads((historical / "warmup-binding-train.json").read_text())["metrics"]
        start = json.loads((folder / "start-natural-train.json").read_text())["metrics"]
        gates[str(seed)] = {}
        for arm, model in models.items():
            name = "revision-" + arm
            save_model(folder, name, model, dict(model_receipt=receipt["models"][arm],
                shared_training_receipt="revision-pair-training.json",
                shared_receipt_sha256=file_digest(folder / "revision-pair-training.json")),
                seed=seed, initial_digest=record["execution_parameter_sha256"])
            old = feedback_panel(folder, name+"-binding-train", model, verifier, provenance,
                parts["reader_train"], bank, arm, binding=True)
            relation = feedback_panel(folder, name+"-binding-internal", model, verifier, provenance,
                parts["internal_tune"], bank, arm, binding=True)
            learned = feedback_panel(folder, name+"-natural-train", model, verifier, provenance,
                natural["train"], bank, arm, binding=False)
            feedback_panel(folder, name+"-augmentation-train", model, verifier, provenance,
                augmentation, bank, arm, binding=True)
            feedback_panel(folder, name+"-natural-internal", model, verifier, provenance,
                natural["tune"], bank, arm, binding=False)
            gates[str(seed)][arm] = joint_gate(old, baseline, relation, learned, start, design["natural_constants"])
            write(folder, name+"-gate.json", gates[str(seed)][arm])
    write(args.output, "feedback-completion.json", dict(gates=gates,
        primary_all_passed=all(g["real"]["passed"] for g in gates.values()), phase_cost=phase_cost(started)))
    freeze_models(args, ["training-completion.json", "feedback-completion.json"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "train", "feedback", "evaluate"))
    for name in ("source", "snapshot", "prepared", "previous-main", "previous-native",
                 "previous-v5", "previous-v6", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.phase == "evaluate":
        from retention_evaluation import evaluate
        evaluate(args)
    else:
        {"prepare": prepare, "train": train, "feedback": feedback}[args.phase](args)


if __name__ == "__main__":
    main()
