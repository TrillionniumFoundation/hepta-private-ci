"""Freeze independent token verifiers/critics, then evaluate actual native control.

Every arm uses raw argmax (ties negative) to isolate stopping from threshold
selection. The frozen Reader was trained without verifier feedback; this study
also measures that inference-time distribution change. No final labels fit the
verifier, critic, cost profile, or stopping policy.
"""
import argparse
import json
from pathlib import Path
import time

import torch

from group_critic import FrozenCritic, _Logistic
from group_encoder import digest_json, file_digest
from multirc_data import score_multirc
from reader_campaign_utils import write_json
from token_calibration import collect_token_critic_rows, fit_token_critic_metered
from token_campaign import SEEDS, inventory, load_models
from token_execution import execute_token_reader
from token_features import TokenBank
from token_prepare import sources
from token_reader import TokenReader
from token_reader_training import fit_token_reader, parameter_digest

ARMS = ("fixed1", "fixed3", "native_ndu", "no_verifier", "reset3")
COHORTS = ("full", "deleted")


def native_inventory():
    return {**inventory(), Path(__file__).name: file_digest(__file__)}


def profile_bounds(model, verifier, receipts):
    maxima = [row["empirical_next_hop_maximum"] for row in receipts]
    if not maxima or any(row["formula_flops"] is None or row["wall_ns"] is None for row in maxima):
        raise ValueError("unsupported empirical native resource profile; freeze/evaluation closed")
    return dict(reader_source_groups=list(model.training_source_groups),
        verifier_source_groups=list(verifier.training_source_groups),
        formula_work_upper=4 * max(row["formula_flops"] for row in maxima),
        duration_upper_ns=max(100_000_000, 4 * max(row["wall_ns"] for row in maxima)),
        formula_work_cap=10**13, wall_time_ns=30_000_000_000, request_ttl_ns=60_000_000_000,
        cost_per_formula_flop=1e-10, cost_per_latency_ns=1e-11,
        discount_rate_per_second=0., minimum_margin=0.)


def load_critic(folder, artifact):
    path = folder / artifact["file"]
    if file_digest(path) != artifact["file_sha256"]:
        raise ValueError("frozen critic file changed")
    model = _Logistic(artifact["metadata"]["feature_width"], 0)
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
    critic = FrozenCritic(model, artifact["metadata"])
    critic.assert_frozen()
    if critic.params_sha256 != artifact["params_sha256"] or digest_json(critic.metadata) != artifact["metadata_sha256"]:
        raise ValueError("frozen critic parameters or metadata changed")
    return critic


def training_inputs(args):
    parts, membership = sources(args.source, args.previous_design)
    design = json.loads((args.campaign / "design.json").read_text())
    if inventory() != design["source_sha256"] or any(design[key] != value for key, value in membership.items()):
        raise ValueError("main campaign source or membership changed")
    frozen = json.loads((args.campaign / "all-models-frozen.json").read_text())
    manifests = {}
    for seed in SEEDS:
        folder = args.campaign / f"seed-{seed}"
        if file_digest(folder / "models.json") != frozen["model_manifests_sha256"][str(seed)]:
            raise ValueError("main selected model manifest changed")
        manifests[seed] = json.loads((folder / "models.json").read_text())
    return parts, membership, frozen, manifests


def train(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    if (args.campaign / "evaluation-start.json").exists():
        raise ValueError("native fitting must precede the first main final evaluation")
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    parts, membership, main_frozen, manifests = training_inputs(args)
    design = dict(membership, schema="hepta.token-reader.native-campaign.v1",
        source_sha256=native_inventory(), native_binary_sha256=file_digest(args.native_binary),
        expected_arms=list(ARMS), expected_cohorts=list(COHORTS), seeds=list(SEEDS),
        main_freeze_sha256=file_digest(args.campaign / "all-models-frozen.json"),
        main_model_manifests_sha256=main_frozen["model_manifests_sha256"],
        verifier=dict(hidden_dim=32, steps=args.steps, depth=1, learning_rate=.003,
                      batch_size=16, evidence_weight=0., counterfactual_train=False),
        critic=dict(steps=80, target="empirical_next_argmax_correctness", threshold_selection=False),
        prediction_rule="argmax_ties_negative_for_all_arms", reader_training_feedback=False,
        verifier_feedback_distribution_shift_measured=True, verifier_acceptance_is_semantic_truth=False,
        cost_bounds="four_times_observed_maximum_complete_trajectory_wall_floor_100ms",
        design_frozen_before_fitting_ns=time.time_ns(), official_validation_labels_used_for_fitting=False,
        strict_equal_compute=False, hosted_ci_consulted=False, production_authorized=False)
    write_json(root, "design.json", design)
    bank = TokenBank.from_snapshot(args.snapshot, batch_size=16, chunk_tokens=64)
    bank.restore_local(args.prepared / "features")
    for seed in SEEDS:
        folder = root / f"seed-{seed}"
        folder.mkdir()
        model = load_models(args.campaign / f"seed-{seed}", manifests[seed])["recurrent"]
        torch.manual_seed(seed)
        verifier, receipt = fit_token_reader(TokenReader(384, 32), bank.dataset(parts["verifier_fit"]),
            steps=args.steps, seed=seed, batch_size=16, max_depth=1, learning_rate=.003,
            counterfactual_fraction=0., evidence_weight=0., diagnostic_interval=args.steps,
            wall_time_ns=1_800_000_000_000)
        write_json(folder, "verifier-training.json", receipt)
        if receipt["completed_steps"] != args.steps:
            raise RuntimeError("incomplete independent verifier fit; final remains closed")
        torch.save(verifier.state_dict(), folder / "verifier.pt")
        outcomes, receipts = [], []
        for name, split in (("critic_fit", "fit"), ("critic_calibration", "calibration")):
            rows, observed = collect_token_critic_rows(model, verifier, bank, parts[name], split=split)
            write_json(folder, name + "-rows.json", rows)
            write_json(folder, name + "-trajectories.json", observed)
            outcomes.append(rows)
            receipts.append(observed)
        critic, fit = fit_token_critic_metered(*outcomes, steps=80, seed=seed)
        write_json(folder, "critic-training.json", fit)
        torch.save(critic.model.state_dict(), folder / "critic.pt")
        manifest = dict(reader_model_sha256=parameter_digest(model),
            verifier=dict(file="verifier.pt", file_sha256=file_digest(folder / "verifier.pt"),
                model_sha256=parameter_digest(verifier), training_source_groups=list(verifier.training_source_groups)),
            critic=dict(file="critic.pt", file_sha256=file_digest(folder / "critic.pt"),
                params_sha256=critic.params_sha256, metadata=critic.metadata,
                metadata_sha256=digest_json(critic.metadata)), profile_bounds=profile_bounds(model, verifier, receipts),
            frozen_before_final_ns=time.time_ns(), final_evaluation_started=False)
        write_json(folder, "artifacts.json", manifest)
        print(json.dumps(dict(seed=seed, verifier_updates=receipt["completed_steps"],
            critic_rows=[len(rows) for rows in outcomes], frozen=True)), flush=True)
    if native_inventory() != design["source_sha256"]:
        raise ValueError("native source changed during fitting")
    write_json(root, "training-bank.json", bank.report())
    write_json(root, "all-artifacts-frozen.json", dict(frozen_ns=time.time_ns(),
        source_sha256=native_inventory(), artifact_manifests_sha256={str(seed):
            file_digest(root / f"seed-{seed}" / "artifacts.json") for seed in SEEDS},
        cpu_ns=time.process_time_ns() - started[1], wall_ns=time.perf_counter_ns() - started[0],
        timing_scope="setup_restore_verifier_fit_public_trajectories_critic_fit_serialization_verification",
        final_evaluation_started=False))


def summarize(cases, rows):
    if [row["case_id"] for row in rows] != [case.case_id for case in cases]:
        raise ValueError("complete aligned question candidates required")
    complete = all(row["prediction"] in (0, 1) for row in rows)
    result = score_multirc(cases, [row["prediction"] for row in rows]) if complete else {}
    costs = [row["request_costs"] for row in rows]
    cpu = [cost["accounted_cpu_ns"] for cost in costs]
    preparation_cpu = sum(row["feature_preparation"]["cpu_ns"] for row in rows)
    preparation_wall = sum(row["feature_preparation"]["wall_ns"] for row in rows)
    result.update(n=len(rows), valid=sum(row["valid"] for row in rows), complete_predictions=complete,
        cpu_ns=sum(cpu) + preparation_cpu if all(value is not None for value in cpu) else None,
        execution_cpu_ns=sum(cpu) if all(value is not None for value in cpu) else None,
        self_cpu_ns=sum(cost["self_cpu_ns"] for cost in costs),
        wall_ns=sum(cost["wall_ns"] for cost in costs) + preparation_wall,
        execution_wall_ns=sum(cost["wall_ns"] for cost in costs),
        feature_preparation_cpu_ns=preparation_cpu, feature_preparation_wall_ns=preparation_wall,
        native_child_cpu_ns=(sum(cost["native_child_cpu_ns"] for cost in costs)
            if all(cost["native_child_cpu_ns"] is not None for cost in costs) else None),
        proposal_steps=sum(row["steps"] for row in rows), native_decisions=sum(row["native_decisions"] for row in rows),
        formula_flops=(sum(cost["complete_formula_flops"] for cost in costs)
            if all(cost["complete_formula_flops"] is not None for cost in costs) else None),
        strict_equal_compute=False, encoder_and_training_excluded_from_online=True,
        timing_scope="sequential_per_answer_public_feature_preparation_plus_execution_including_artifact_rehashes_and_meter",
        feature_preparation_in_cpu_and_wall=True, native_wall_already_in_execution_wall=True)
    return result


def evaluate(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    root = args.output
    design = json.loads((root / "design.json").read_text())
    frozen = json.loads((root / "all-artifacts-frozen.json").read_text())
    parts, membership, _, manifests = training_inputs(args)
    if (native_inventory() != design["source_sha256"] or native_inventory() != frozen["source_sha256"]
            or file_digest(args.native_binary) != design["native_binary_sha256"]
            or file_digest(args.campaign / "all-models-frozen.json") != design["main_freeze_sha256"]
            or any(design[key] != value for key, value in membership.items())):
        raise ValueError("native frozen source, binary, membership or main selection changed")
    if not (args.campaign / "completion.json").is_file():
        raise ValueError("main frozen final evaluation must complete before native evaluation")
    main_start = json.loads((args.campaign / "evaluation-start.json").read_text())
    if (not 0 < frozen["frozen_ns"] < main_start["started_ns"]
            or main_start["all_models_frozen_sha256"] != design["main_freeze_sha256"]
            or main_start["source_sha256"] != inventory()):
        raise ValueError("native artifacts must freeze before the first main final evaluation")
    bank = TokenBank.from_snapshot(args.snapshot, batch_size=16, chunk_tokens=64)
    bank.restore_local(args.campaign / "evaluation-features")
    cases = parts["final"]
    all_summaries = {}
    for seed in SEEDS:
        folder = root / f"seed-{seed}"
        if file_digest(folder / "artifacts.json") != frozen["artifact_manifests_sha256"][str(seed)]:
            raise ValueError("native model selection changed after freeze")
        artifact = json.loads((folder / "artifacts.json").read_text())
        model = load_models(args.campaign / f"seed-{seed}", manifests[seed])["recurrent"]
        verifier_path = folder / artifact["verifier"]["file"]
        if file_digest(verifier_path) != artifact["verifier"]["file_sha256"]:
            raise ValueError("frozen verifier file changed")
        verifier = TokenReader(384, 32)
        verifier.load_state_dict(torch.load(verifier_path, map_location="cpu", weights_only=True), strict=True)
        verifier.eval().requires_grad_(False)
        verifier.training_source_groups = tuple(artifact["verifier"]["training_source_groups"])
        if parameter_digest(model) != artifact["reader_model_sha256"] or parameter_digest(verifier) != artifact["verifier"]["model_sha256"]:
            raise ValueError("frozen reader/verifier parameters changed")
        critic = load_critic(folder, artifact["critic"])
        destination = folder / "final"
        destination.mkdir()
        protocol = dict(design, seed=seed, artifact_manifest_sha256=file_digest(folder / "artifacts.json"),
                        models_frozen_before_final_ns=frozen["frozen_ns"], final_evaluation_started_ns=time.time_ns())
        write_json(destination, "protocol.json", protocol)
        rows, summaries = [], {}
        for cohort in COHORTS:
            for arm in ARMS:
                panel = []
                trace_name = f"executions-{cohort}-{arm}.jsonl"
                with (destination / trace_name).open("x") as trace:
                    for line, case in enumerate(cases, 1):
                        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                        public = bank.public(case, deleted=cohort == "deleted")
                        preparation = dict(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall)
                        result = execute_token_reader(public, model, verifier, critic, mode=arm,
                            profile_bounds=artifact["profile_bounds"], native_binary=args.native_binary)
                        trace.write(json.dumps(dict(case_id=case.case_id, execution=result), sort_keys=True) + "\n")
                        row = dict(case_id=case.case_id, arm=arm, cohort=cohort, prediction=result["prediction"],
                            p_positive=result["step_records"][-1]["probabilities"][1] if result["step_records"] else None,
                            valid=result["status"] != "callback_failed" and not result["native_support_violated"]
                                and not result["native_controller_failed_closed"], status=result["status"],
                            steps=result["steps"], native_decisions=len(result["native_control_decisions"]),
                            feature_sha256=result["feature_sha256"], source_sha256=result["source_sha256"],
                            tensor_sha256=result["tensor_sha256"], artifact_digests=result["artifact_digests_before"],
                            request_costs=result["request_costs"], feature_preparation=preparation,
                            trace_file=trace_name, trace_line=line, protocol_sha256=digest_json(protocol))
                        panel.append(row)
                rows.extend(panel)
                write_json(destination, "observations.json", rows)
                summaries[f"{cohort}.{arm}"] = summarize(cases, panel)
                write_json(destination, "report.json", dict(summaries=summaries, strict_equal_compute=False))
                print(json.dumps(dict(seed=seed, cohort=cohort, arm=arm, n=len(panel),
                    **{key: summaries[f"{cohort}.{arm}"].get(key) for key in ("f1_a", "cpu_ns", "proposal_steps")})), flush=True)
        all_summaries[str(seed)] = summaries
    if native_inventory() != design["source_sha256"] or file_digest(args.native_binary) != design["native_binary_sha256"]:
        raise ValueError("source or native binary changed during evaluation")
    write_json(root, "evaluation-bank.json", bank.report())
    write_json(root, "completion.json", dict(completed_ns=time.time_ns(), summaries=all_summaries,
        cpu_ns=time.process_time_ns() - started[1], wall_ns=time.perf_counter_ns() - started[0],
        source_sha256=native_inventory(), repeated_seeds_are_independent_examples=False,
        prediction_rule="argmax_ties_negative_for_all_arms", strict_equal_compute=False,
        hosted_ci_consulted=False, production_authorized=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("train", "evaluate"))
    for name in ("campaign", "prepared", "source", "snapshot", "previous-design", "native-binary", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--steps", type=int, default=512)
    args = parser.parse_args()
    torch.set_num_threads(1)
    (train if args.phase == "train" else evaluate)(args)


if __name__ == "__main__":
    main()
