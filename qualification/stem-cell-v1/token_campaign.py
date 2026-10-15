"""Train-internal V4 selection, then frozen evaluation on fresh official paragraphs."""
import argparse
import json
from pathlib import Path
import time

import torch

from group_encoder import digest_json, file_digest
from multirc_data import score_multirc
from reader_campaign import source_inventory as old_inventory
from reader_campaign_utils import write_json
from token_campaign_utils import (ARMS, ARM_DEPTHS, COHORTS, DeletedDataset, choose_threshold,
                                  evaluate_panel, evidence_deltas, infer)
from token_features import TokenBank
from token_prepare import sources
from token_protocol import build_binding_cases, score_binding
from token_reader import TokenReader
from token_reader_training import fit_token_reader, parameter_digest

SEEDS = (41, 47, 53)
TRAINED_ARMS = ("pooled", "token", "intervention", "recurrent", "query_only")


def inventory():
    root = Path(__file__).parent
    result = old_inventory()
    result.update({path.name: file_digest(path) for path in root.glob("token*.py")
                   if path.name != "token_native_campaign.py"})
    return dict(sorted(result.items()))


def get_bank(args):
    bank = TokenBank.from_snapshot(args.snapshot, batch_size=16, chunk_tokens=64)
    bank.restore_local(args.prepared / "features")
    return bank


def train(args):
    phase_started = time.perf_counter_ns(), time.process_time_ns()
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    parts, membership = sources(args.source, args.previous_design)
    if membership != {k: v for k, v in json.loads((args.prepared / "membership.json").read_text()).items()
                      if k in membership}:
        raise ValueError("prepared source selection differs")
    gate = json.loads((args.gate / "report.json").read_text())
    gate_protocol = json.loads((args.gate / "protocol.json").read_text())
    if not gate["passed"] or gate["official_validation_evaluated"]:
        raise ValueError("tiny train-only fitting gate did not pass")
    for name, expected in gate_protocol["model_source_sha256"].items():
        if file_digest(Path(__file__).parent / name) != expected:
            raise ValueError("gate implementation changed")
    synthetic = build_binding_cases("train", groups=32, seed=41)
    design = dict(**membership, source_sha256=inventory(), seeds=list(SEEDS),
        expected_arms=list(ARMS), expected_cohorts=list(COHORTS), arm_depths=ARM_DEPTHS,
        arm_input_transforms={arm: "delete_evidence" if arm == "query_only" else "identity" for arm in ARMS},
        selected_hyperparameters=dict(hidden_dim=32, steps=args.steps, batch_size=16, learning_rate=.003,
            evidence_weight=.2, intervention_probability=.25, optimizer="Adam_foreach_false"),
        threshold_grid=[i / 20 for i in range(1, 20)],
        threshold_selection="internal_tune_F1a_then_EM_then_nearest_0.5_then_lower",
        synthetic_groups=dict(train=32, tune=16, final=32), synthetic_seed=41,
        gate_report_sha256=file_digest(args.gate / "report.json"), gate=gate,
        training_majority_prediction=int(sum(case.label for case in parts["train"]) * 2 >= len(parts["train"])),
        design_frozen_before_fitting_ns=time.time_ns(), strict_equal_compute=False,
        all_scored_validation_source_hashes=sorted(set(membership["partitions"]["final"])
            | set(membership["previous_final_source_hashes"])),
        natural_official_evidence_annotations_used=False, encoder_trained=False,
        hosted_ci_consulted=False, production_authorized=False)
    write_json(root, "design.json", design)
    bank = get_bank(args)
    started = time.perf_counter_ns(), time.process_time_ns()
    for seed in SEEDS:
        folder = root / f"seed-{seed}"
        folder.mkdir()
        model_map, training, artifacts = {}, {}, {}
        for arm in TRAINED_ARMS:
            torch.manual_seed(seed)
            train_data, tune_data = bank.dataset(parts["train"]), bank.dataset(parts["tune"])
            if arm == "query_only":
                train_data, tune_data = DeletedDataset(train_data), DeletedDataset(tune_data)
            auxiliary = arm in ("intervention", "recurrent")
            model, receipt = fit_token_reader(TokenReader(384, 32, interaction="pooled" if arm == "pooled" else "token"),
                train_data, tune_data, steps=args.steps, seed=seed, batch_size=16,
                max_depth=ARM_DEPTHS[arm], learning_rate=.003,
                counterfactual_train=bank.dataset(synthetic) if auxiliary else None,
                evidence_weight=.2 if auxiliary else 0, diagnostic_interval=args.steps,
                wall_time_ns=1_800_000_000_000)
            training[arm] = receipt
            write_json(folder, "training.json", training)
            if receipt["completed_steps"] != args.steps:
                raise RuntimeError("incomplete training; final evaluation remains closed")
            path = folder / f"{arm}.pt"
            torch.save(model.state_dict(), path)
            artifacts[arm] = dict(file=path.name, file_sha256=file_digest(path),
                model_sha256=parameter_digest(model), interaction=model.interaction,
                training_source_groups=list(model.training_source_groups))
            model_map[arm] = model
            print(json.dumps(dict(seed=seed, trained=arm, updates=receipt["completed_steps"],
                cpu_ns=receipt["cpu_ns"], final_diagnostic=receipt["diagnostics"][-1])), flush=True)
        model_map.update(one_step=model_map["recurrent"], reset_state=model_map["recurrent"])
        tuning, tuning_batches = {}, []
        for arm in ARMS:
            probabilities, costs = infer(model_map[arm], parts["tune"], bank, depth=ARM_DEPTHS[arm],
                deleted=arm == "query_only", reset=arm == "reset_state", prefix=f"tune/{seed}/{arm}")
            selection = choose_threshold(parts["tune"], probabilities)
            selection.update(case_ids=[case.case_id for case in parts["tune"]], probabilities=probabilities)
            tuning[arm] = selection
            tuning_batches.extend(costs)
        write_json(folder, "tuning.json", tuning)
        write_json(folder, "tuning-inference-batches.json", tuning_batches)
        write_json(folder, "models.json", dict(models=artifacts,
            arm_model_names={arm: "recurrent" if arm in ("one_step", "reset_state") else arm for arm in ARMS},
            arm_thresholds={arm: row["threshold"] for arm, row in tuning.items()},
            frozen_before_final_ns=time.time_ns(), final_evaluation_started=False))
    if inventory() != design["source_sha256"]:
        raise ValueError("runtime source changed during fitting")
    write_json(root, "all-models-frozen.json", dict(seeds=list(SEEDS), frozen_ns=time.time_ns(),
        model_manifests_sha256={str(seed): file_digest(root / f"seed-{seed}" / "models.json") for seed in SEEDS},
        cpu_ns=time.process_time_ns() - started[1], wall_ns=time.perf_counter_ns() - started[0],
        final_evaluation_started=False))
    write_json(root, "training-bank.json", bank.report())
    write_json(root, "training-phase-cost.json", dict(cpu_ns=time.process_time_ns() - phase_started[1],
        wall_ns=time.perf_counter_ns() - phase_started[0],
        includes="source_setup_encoder_reload_restore_initialization_fit_tuning_hashing_serialization_verification",
        nested_costs_additive=False))


def load_models(folder, manifest):
    models = {}
    for name, artifact in manifest["models"].items():
        path = folder / artifact["file"]
        if file_digest(path) != artifact["file_sha256"]:
            raise ValueError("frozen model file changed")
        model = TokenReader(384, 32, interaction=artifact["interaction"])
        model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
        model.eval().requires_grad_(False)
        model.training_source_groups = tuple(artifact["training_source_groups"])
        if parameter_digest(model) != artifact["model_sha256"]:
            raise ValueError("frozen model parameters changed")
        models[name] = model
    return {arm: models[name] for arm, name in manifest["arm_model_names"].items()}


def evaluate(args):
    phase_started = time.perf_counter_ns(), time.process_time_ns()
    root = args.output
    design = json.loads((root / "design.json").read_text())
    if inventory() != design["source_sha256"]:
        raise ValueError("runtime source changed after fitting")
    frozen = json.loads((root / "all-models-frozen.json").read_text())
    write_json(root, "evaluation-start.json", dict(started_ns=time.time_ns(),
        all_models_frozen_sha256=file_digest(root / "all-models-frozen.json"),
        source_sha256=inventory()))
    parts, membership = sources(args.source, args.previous_design)
    if any(design[key] != value for key, value in membership.items()):
        raise ValueError("evaluation source membership changed")
    models = {}
    for seed in SEEDS:
        folder = root / f"seed-{seed}"
        if file_digest(folder / "models.json") != frozen["model_manifests_sha256"][str(seed)]:
            raise ValueError("model selection changed after freeze")
        models[seed] = load_models(folder, json.loads((folder / "models.json").read_text()))
    bank = get_bank(args)
    binding = build_binding_cases("final", groups=32, seed=41)
    before = dict(cpu_ns=bank.cpu_ns, wall_ns=bank.wall_ns)
    for cases in (parts["final"], parts["regression"], binding):
        bank.register(cases)
    increment = {key: getattr(bank, key) - value for key, value in before.items()}
    for seed in SEEDS:
        manifest = json.loads((root / f"seed-{seed}" / "models.json").read_text())
        for partition, cases in (("final", parts["final"]), ("regression", parts["regression"]), ("binding", binding)):
            folder = root / f"seed-{seed}" / partition
            folder.mkdir()
            features = {cohort: {case.case_id: bank.public(case, deleted=cohort == "deleted")["feature_sha256"]
                                 for case in cases} for cohort in COHORTS}
            protocol = dict(design, seed=seed, evaluation_partition=partition,
                final_case_ids=[case.case_id for case in cases], public_feature_sha256=features,
                final_question_candidate_ids={json.dumps(key, separators=(",", ":")):
                    [case.case_id for case in cases if case.question_key == key] for key in
                    sorted({case.question_key for case in cases})},
                arm_thresholds=manifest["arm_thresholds"],
                arm_model_sha256={arm: parameter_digest(model) for arm, model in models[seed].items()},
                models_frozen_before_final_ns=frozen["frozen_ns"])
            write_json(folder, "protocol.json", protocol)
            rows, costs, summaries = evaluate_panel(models[seed], cases, bank, protocol, prefix=f"{seed}/{partition}")
            write_json(folder, "observations.json", rows)
            write_json(folder, "inference-batches.json", costs)
            if partition == "binding":
                write_json(folder, "controlled-cases.json", [dict(case_id=c.case_id, paragraph_id=c.paragraph_id,
                    question=c.question, candidate=c.candidate, facts=c.facts, source_hash=c.source_hash,
                    label=c.label, segmentation=c.segmentation) for c in cases])
                for key, summary in summaries.items():
                    cohort, arm = key.split(".")
                    selected = [row for row in rows if row["cohort"] == cohort and row["arm"] == arm]
                    summary.update(score_binding(cases, [row["prediction"] for row in selected]))
            report = dict(protocol_sha256=digest_json(protocol), summaries=summaries, evidence_deltas=evidence_deltas(rows),
                baselines={name: score_multirc(cases, [prediction] * len(cases)) for name, prediction in
                           (("all_positive", 1), ("all_negative", 0), ("training_majority", design["training_majority_prediction"]))},
                strict_equal_compute=False, repeated_seeds_are_independent_examples=False)
            write_json(folder, "report.json", report)
            print(json.dumps(dict(seed=seed, partition=partition, completed=len(rows))), flush=True)
    bank.save_local(root / "evaluation-features")
    write_json(root, "evaluation-encoder.json", dict(bank.report(), evaluation_incremental_cost=increment))
    if inventory() != design["source_sha256"]:
        raise ValueError("runtime source changed during final evaluation")
    write_json(root, "completion.json", dict(seeds=list(SEEDS), completed_ns=time.time_ns(),
        source_sha256=inventory(), hosted_ci_consulted=False, production_authorized=False,
        strict_equal_compute=False))
    write_json(root, "evaluation-phase-cost.json", dict(cpu_ns=time.process_time_ns() - phase_started[1],
        wall_ns=time.perf_counter_ns() - phase_started[0],
        includes="setup_restore_incremental_encode_hashing_inference_metrics_serialization_verification",
        nested_costs_additive=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("train", "evaluate"))
    for name in ("source", "snapshot", "previous-design", "prepared", "gate", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--steps", type=int, default=512)
    args = parser.parse_args()
    torch.set_num_threads(1)
    (train if args.phase == "train" else evaluate)(args)


if __name__ == "__main__":
    main()
