"""Actual MultiRC Reader fitting, source-held-out controls and online native NDU.

Run only after a train-only learnability gate. Public validation is a held-out
subset, not an official test score. Native utility optimizes a correctness
surrogate, not the nonadditive benchmark F1/EM. No CI result is consulted.
"""
import argparse
import json
from pathlib import Path
import time

import torch

from group_encoder import FrozenTokenEncoder, digest_json, file_digest
from group_loop import parameter_digest
from group_reader import Reader
from group_reader_training import fit_reader
from multirc_data import load_jsonl, partition_cases
from reader_budget import allocate_shared_feature_cost, freeze_frontier_bins, summarize_work_frontier
from reader_calibration import collect_critic_rows, fit_critic_metered
from reader_campaign_utils import (ARMS, COHORTS, PARAGRAPH_CAPS, deleted_batch, freeze_manifest, gate_cases,
                                   select_paragraphs, summarize, training_feedback, write_json)
from reader_execution import execute_reader
from reader_features import SentenceBank

DATA_HASHES = dict(train="bb73d0838618f8269190a2533fead3140607558975ea0df6511fa534e8d3535c",
                   validation="d2b480195b15574ac00d52c4479f630bc161a7ab2de77e970fd00652846953ee")


def source_inventory():
    root = Path(__file__).parent
    names = {path.name for pattern in ("reader*.py", "group_reader*.py", "multirc*.py")
             for path in root.glob(pattern) if not path.name.startswith("test_")}
    names.update(("native_group_control.py", "group_encoder.py", "group_critic.py", "group_loop.py",
                  "system2_execution.py", "execution_meter.py", "aten_work.py", "transformer_work.py",
                  "native_ndu_bridge.py", "hf_encoder_kernel.py", "host_counters.py", "paired_execution.py",
                  "next_round_matrix.py", "ndu_continuation.py", "group_features.py"))
    return {name: file_digest(root / name) for name in sorted(names)}


def native_status_valid(result):
    return (result["prediction"] in (0, 1)
            and result["status"] in {"depth_exhausted", "utility_stop", "verifier_accepted_not_independent_eval"}
            and not result["native_support_violated"]
            and not result.get("native_controller_failed_closed", False)
            and result["artifact_digests_before"] == result["artifact_digests_after"])


def run_seed(root, seed, parts, bank, design, native_binary, steps):
    root.mkdir(parents=True, exist_ok=False)
    train, tune, vf = (bank.batch(parts[name]) for name in ("train", "tune", "verifier_fit"))
    models, training = {}, {}
    # The independent verifier is trained on paragraphs excluded from the Reader.
    torch.manual_seed(seed)
    models["verifier"], training["verifier"] = fit_reader(
        Reader(384, 32), vf, tune, steps=steps, seed=seed, max_depth=1,
        learning_rate=.01, wall_time_ns=900_000_000_000)
    feedback = training_feedback(models["verifier"])
    for name, depth, data, validation in (("static", 1, train, tune), ("core", 3, train, tune),
                                          ("query_only", 3, deleted_batch(train), deleted_batch(tune))):
        torch.manual_seed(seed)
        models[name], training[name] = fit_reader(
            Reader(384, 48), data, validation, steps=steps, seed=seed, max_depth=depth,
            learning_rate=.01, feedback_fn=feedback if depth > 1 else None,
            wall_time_ns=900_000_000_000)
        write_json(root, "training.json", training)
        print(json.dumps(dict(seed=seed, trained=name, updates=training[name]["completed_steps"],
                              diagnostic=training[name]["diagnostics"][-1])), flush=True)
    if any(receipt["completed_steps"] != steps for receipt in training.values()):
        raise RuntimeError("incomplete real training retained; final evaluation not started")
    rows, fit_rollout = collect_critic_rows(models["core"], models["verifier"], bank,
                                           parts["critic_fit"], split="validation_fit")
    calibration, calibration_rollout = collect_critic_rows(models["core"], models["verifier"], bank,
        parts["critic_calibration"], split="validation_calibration")
    critic, critic_fit = fit_critic_metered(rows, calibration, steps=80, seed=seed)
    write_json(root, "critic-fit-rollouts.json", fit_rollout)
    write_json(root, "critic-calibration-rollouts.json", calibration_rollout)
    write_json(root, "critic-fit.json", critic_fit)
    maximum = {key: max(fit_rollout["empirical_next_hop_maximum"][key],
                        calibration_rollout["empirical_next_hop_maximum"][key])
               for key in ("formula_flops", "wall_ns")}
    bounds = dict(reader_source_groups=design["partitions"]["train"],
                  verifier_source_groups=design["partitions"]["verifier_fit"], verifier_threshold=.9,
                  duration_upper_ns=max(100_000_000, 4 * maximum["wall_ns"]),
                  formula_work_upper=max(1_000_000, 4 * maximum["formula_flops"]),
                  cost_per_formula_flop=1e-10, cost_per_latency_ns=1e-11,
                  wall_time_ns=30_000_000_000, formula_work_cap=10**10,
                  request_ttl_ns=60_000_000_000)
    model_names = {arm: "static" if arm == "static" else "query_only" if arm == "query_only" else "core"
                   for arm in ARMS}
    protocol = {**design, "seed": seed,
        "arm_model_sha256": {arm: parameter_digest(models[name]) for arm, name in model_names.items()},
        "critic_sha256": critic.params_sha256, "verifier_sha256": parameter_digest(models["verifier"]),
        "profile_bounds": bounds, "profile_observed_maxima_are_future_guarantees": False,
        "models_frozen_before_final_ns": time.time_ns()}
    protocol_sha = digest_json(protocol)
    write_json(root, "protocol.json", protocol)
    observations, traces, summaries = [], {}, {}
    for cohort in COHORTS:
        for arm in ARMS:
            panel = []
            for index, case in enumerate(parts["final"]):
                started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
                effective = "deleted" if arm == "query_only" else cohort
                public = bank.public(case, deleted=effective == "deleted", permuted=effective == "permuted")
                mode = "fixed" if arm in {"one_step", "query_only"} else arm
                try:
                    result = execute_reader(public, models[model_names[arm]], models["verifier"], critic,
                        mode=mode, max_steps=1 if arm == "one_step" else 3,
                        native_binary=native_binary, profile_bounds=bounds)
                except Exception as error:
                    write_json(root, "observations.json", observations + panel)
                    write_json(root, "interrupted-case.json", dict(case_id=case.case_id, arm=arm, cohort=cohort,
                        cpu_ns=time.process_time_ns() - started_cpu,
                        wall_ns=time.perf_counter_ns() - started_wall,
                        error_type=type(error).__name__, message=str(error), valid=False))
                    raise
                cpu_ns, wall_ns = time.process_time_ns() - started_cpu, time.perf_counter_ns() - started_wall
                child_cpu = result["native_child_cpu_ns"]
                row = dict(case_id=case.case_id, paragraph_id=case.paragraph_id, question_id=case.question_id,
                    answer_id=case.answer_id, source_hash=case.source_hash, cohort=cohort, arm=arm,
                    prediction=result["prediction"], target=case.label, valid=native_status_valid(result),
                    status=result["status"], steps=result["steps"], cpu_ns=cpu_ns, wall_ns=wall_ns,
                    native_child_cpu_ns=child_cpu, native_subprocess_wall_ns=result["native_child_wall_ns"],
                    total_online_cpu_ns=None if child_cpu is None else cpu_ns + child_cpu,
                    formula_flops=result["end_to_end_formula_flops"],
                    covered_aten_formula_flops=result["work_observation"]["phase_flops"]["search"],
                    model_sha256=result["model_sha256"], feature_sha256=result["feature_sha256"],
                    protocol_sha256=protocol_sha, native_calls=len(result["native_control_decisions"]),
                    native_failed_closed=result.get("native_controller_failed_closed", False))
                panel.append(row)
                if index < 2:
                    traces[cohort + "." + arm + "." + str(index)] = result
            observations.extend(panel)
            write_json(root, "observations.json", observations)
            write_json(root, "trace-samples.json", traces)
            summaries[cohort + "." + arm] = summarize(parts["final"], panel, design["training_majority_prediction"])
            print(json.dumps(dict(seed=seed, cohort=cohort, arm=arm, **summaries[cohort + "." + arm])), flush=True)
    frontier_rows = [dict(case_id=r["case_id"], arm=r["arm"], source_group=r["source_hash"],
        source_id=protocol_sha, split="heldout_validation", success=r["prediction"] == r["target"],
        qualified=r["valid"], formula_flops=r["formula_flops"], cpu_ns=r["cpu_ns"], wall_ns=r["wall_ns"],
        native_child_cpu_ns=r["native_child_cpu_ns"],
        formula_source="operator_formula_complete.v1" if r["formula_flops"] is not None else None)
        for r in observations if r["cohort"] == "full"]
    frontier = {metric: summarize_work_frontier(frontier_rows, spec, preregistered_protocol_id=spec["protocol_id"])
                for metric, spec in design["frontier_protocols"].items()}
    write_json(root, "actual-work-frontiers.json", frontier)
    report = dict(schema="hepta.multirc.reader-campaign.v1", seed=seed, protocol_sha256=protocol_sha,
        summaries=summaries, training=training, critic=critic_fit,
        final_evaluation_started_after_frozen_models=True, native_online_control=True,
        native_production_owner_integrated=False, verifier_acceptance_is_semantic_truth=False,
        complete_cost_qualification=False, strict_equal_compute=False,
        scope="fixed_public_validation_subset_not_official_test_score",
        objective="candidate_correctness_surrogate_not_direct_F1_optimization")
    write_json(root, "report.json", report)
    return observations


def campaign(args):
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    gate = json.loads((args.gate / "report.json").read_text())
    gate_protocol = json.loads((args.gate / "protocol.json").read_text())
    if gate.get("passed") is not True or gate.get("official_validation_accessed") is not False:
        raise ValueError("train-only optimization learnability gate must pass first")
    for name, expected in gate["source_sha256"].items():
        if file_digest(Path(__file__).parent / name) != expected:
            raise ValueError("learnability gate belongs to another Reader implementation")
    train = load_jsonl(args.source / "train.jsonl", "train")
    if train.sha256 != DATA_HASHES["train"] or gate_protocol["dataset_train_sha256"] != train.sha256:
        raise ValueError("official train bytes changed")
    parts = partition_cases(train.cases, seed=41)
    parts = {name: select_paragraphs(cases, PARAGRAPH_CAPS[name]) for name, cases in parts.items() if name != "final"}
    load_start = time.perf_counter_ns(), time.process_time_ns()
    encoder = FrozenTokenEncoder(args.snapshot, max_tokens=256)
    loading = dict(wall_ns=time.perf_counter_ns() - load_start[0], cpu_ns=time.process_time_ns() - load_start[1])
    bank = SentenceBank(encoder, batch_size=16)
    bank.restore_local(args.feature_cache)
    gate_selected = gate_cases(parts["train"], questions=8)
    bank.register(gate_selected)
    if (gate_protocol["case_ids"] != [case.case_id for case in gate_selected]
            or gate_protocol["feature_sha256"] != [bank.public(case)["feature_sha256"] for case in gate_selected]
            or gate_protocol["source_sha256"] != gate["source_sha256"]):
        raise ValueError("learnability gate used different public features or sources")
    # This is the first opening of official validation in this campaign, after the gate.
    final = load_jsonl(args.source / "val.jsonl", "validation")
    if final.sha256 != DATA_HASHES["validation"]:
        raise ValueError("official validation bytes changed")
    parts["final"] = select_paragraphs(final.cases, PARAGRAPH_CAPS["final"])
    manifest = freeze_manifest(parts)
    for name, cases in parts.items():
        if name != "final":
            bank.register(cases)
    feature_before = dict(cpu_ns=bank.cpu_ns, wall_ns=bank.wall_ns)
    bank.register(parts["final"])
    final_feature_cost = {key: getattr(bank, key) - feature_before[key] for key in feature_before}
    features = {cohort: {case.case_id: bank.public(case, deleted=cohort == "deleted",
                permuted=cohort == "permuted")["feature_sha256"] for case in parts["final"]} for cohort in COHORTS}
    majority = int(sum(case.label for case in parts["train"]) * 2 >= len(parts["train"]))
    sources = source_inventory()
    membership = [dict(case_id=case.case_id, arm=arm, source_group=case.source_hash,
                       split="heldout_validation") for case in parts["final"] for arm in ARMS]
    frontiers = {metric: freeze_frontier_bins(observations=membership, arms=ARMS, metric=metric, edges=edges)
                 for metric, edges in (("cpu_ns", [0, 2_000_000, 5_000_000, 10_000_000, 20_000_000,
                     50_000_000, 100_000_000, 500_000_000, 2_000_000_000]),
                     ("formula_flops", [0, 1_000_000, 3_000_000, 10_000_000, 30_000_000, 100_000_000, 1_000_000_000]))}
    design = dict(schema="hepta.multirc.reader-protocol.v1", **manifest, source_sha256=sources,
        dataset_files_sha256={"train.jsonl": train.sha256, "val.jsonl": final.sha256},
        dataset_counts=dict(train=train.counts, validation=final.counts), paragraph_caps=PARAGRAPH_CAPS,
        expected_arms=list(ARMS), expected_cohorts=list(COHORTS), final_partition="final",
        selected_hyperparameters=dict(hidden_dim=48, verifier_hidden_dim=32, steps=args.steps,
            optimizer="Adam", learning_rate=.01, batch_size=32, max_depth=3, verifier_threshold=.9),
        training_majority_prediction=majority, public_feature_sha256=features,
        arm_input_transforms={arm: "delete_evidence" if arm == "query_only" else "identity" for arm in ARMS},
        gate_report_sha256=file_digest(args.gate / "report.json"),
        gate_protocol_sha256=file_digest(args.gate / "protocol.json"), gate=gate,
        seeds=[41, 47, 53], frontier_protocols=frontiers,
        native_binary_sha256=file_digest(args.native_binary), design_frozen_before_fitting_ns=time.time_ns(),
        strict_equal_compute=False, final_subset_label_independent=True,
        permutation_cohort_scope="set_stability_not_order_reasoning", production_authorized=False)
    write_json(root, "design.json", design)
    all_rows = []
    for seed in (41, 47, 53):
        all_rows.extend((seed, row) for row in run_seed(root / f"seed-{seed}", seed, parts, bank,
                                                      design, args.native_binary, args.steps))
    feature_receipt = bank.report()
    origin = json.loads((args.feature_cache / "encoder.json").read_text())
    write_json(root, "encoder.json", dict(**feature_receipt, current_loading=loading,
        cache_origin=str(args.feature_cache), cache_origin_loading=origin.get("loading"),
        cache_origin_receipt_sha256=file_digest(args.feature_cache / "encoder.json"),
        local_cache_sha256=file_digest(args.feature_cache / "vectors.pt"), final_incremental_cost=final_feature_cost,
        origin_encoding_cpu_and_wall_measured=True, total_preparation_cost_qualification=False))
    uses = [dict(use_id=f"{seed}/{row['cohort']}/{row['arm']}/{row['case_id']}",
                 feature_id=feature_receipt["feature_set_sha256"], source_id=row["feature_sha256"], observed=True)
            for seed, row in all_rows]
    allocation = allocate_shared_feature_cost(dict(feature_id=feature_receipt["feature_set_sha256"],
        source_id=digest_json(final_feature_cost), **final_feature_cost, formula_flops=None,
        native_child_cpu_ns=0, formula_source=None), uses)
    write_json(root, "final-shared-feature-allocation.json", allocation)
    if sources != source_inventory() or file_digest(args.native_binary) != design["native_binary_sha256"]:
        raise ValueError("implementation or native binary changed during the campaign")
    write_json(root, "completion.json", dict(completed_seeds=[41, 47, 53], observations=len(all_rows),
        wall_ns=time.perf_counter_ns() - started_wall, cpu_ns=time.process_time_ns() - started_cpu,
        complete_cost_qualification=False, hosted_ci_consulted=False, production_authorized=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "source", "feature-cache", "gate", "output", "native-binary"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--steps", type=int, default=512)
    args = parser.parse_args()
    import torch._dynamo
    campaign(args)


if __name__ == "__main__":
    main()
