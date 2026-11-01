"""Frozen eight-fit inference and measured research-cost accounting for R14."""

import argparse
import json
from pathlib import Path

import numpy as np

from ..unified_cell_r12_20261031.statistics import exact_sign_flip, holm_adjust, paired_summary


DOMAINS = ("iid", "ood")
ARMS = ("A", "B", "C", "D")
METRICS = ("utility", "reward", "fee", "reads", "resets", "elapsed")
REUSES = (1, 100, 1000, 10000)
OFFLINE_KEYS = ("preparation_cpu_seconds", "common_calibration_cpu_seconds",
                "ordinary_candidate_and_selection_cpu_seconds", "hx_candidate_and_validation_cpu_seconds",
                "ce_counterfactual_additional_actual_cpu_seconds", "total_process_cpu_seconds")


def _number(value, name, nonnegative=False):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number))
            or not np.isfinite(value) or (nonnegative and value < 0)):
        raise ValueError("Invalid measured value: " + name)
    return float(value)


def _execution(item, episodes):
    if item.get("count") != episodes:
        raise ValueError("Confirmation episode count differs from preregistration")
    for metric in METRICS:
        _number(item["mean"][metric], metric, metric != "utility")
    if item["mean"]["reward"] > 1 + 1e-12:
        raise ValueError("Terminal correctness cannot exceed one")
    for metric in ("utility", "reward", "fee", "reads", "resets"):
        values = np.asarray(item["episode_values"][metric], dtype=float)
        if values.shape != (episodes,) or not np.isfinite(values).all():
            raise ValueError("Incomplete raw episode evidence")
        if abs(values.mean() - item["mean"][metric]) > 1e-10:
            raise ValueError("Aggregate differs from retained episode values")
    if abs(item["mean"]["utility"] - item["mean"]["reward"] + item["mean"]["fee"]) > 1e-10:
        raise ValueError("Utility does not include the actual task fees")
    costs = item["costs"]
    for key in ("cpu_seconds", "inference_cpu_seconds", "control_cpu_seconds",
                "planner_construction_cpu_seconds", "owner_cpu_seconds"):
        _number(costs[key], key, True)
    _number(costs.get("model_preparation_cpu_seconds", 0.), "model_preparation_cpu_seconds", True)
    if not item.get("tape_hash") or not item.get("planner_identity") or not item.get("world_identity"):
        raise ValueError("Missing tape or model identity")


def _indexed(rows, protocol):
    seeds = protocol["fit_seeds"]
    if len(seeds) != 8 or len(set(seeds)) != 8 or len(rows) != 16:
        raise ValueError("Exactly eight preregistered paired fits and two domains are required")
    indexed = {domain: {} for domain in DOMAINS}
    training_by_seed = {}
    provenance = None
    for row in rows:
        domain, seed = row.get("domain"), row.get("seed")
        if (domain not in DOMAINS or seed not in seeds or isinstance(seed, bool)
                or not isinstance(seed, (int, np.integer)) or seed in indexed[domain]):
            raise ValueError("Unexpected or duplicate confirmation domain/seed")
        identity = tuple(row.get(key) for key in ("source_commit", "freeze_commit", "freeze_sha256"))
        for value, size in zip(identity, (40, 40, 64)):
            if not isinstance(value, str) or len(value) != size or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("Missing exact source or candidate-freeze identity")
        if provenance is not None and identity != provenance:
            raise ValueError("Confirmation cohort mixes source or candidate freezes")
        provenance = identity
        _number(row["owner_setup_cpu_seconds"], "owner_setup_cpu_seconds", True)
        _number(row["total_process_cpu_seconds"], "confirmation total CPU", True)
        if set(row.get("arms", {})) != set(ARMS):
            raise ValueError("Every fit must retain the complete A/B/C/D comparison")
        training = row["training"]
        if training.get("seed") != seed or training.get("status") != "completed":
            raise ValueError("Confirmation refers to an incomplete or different training fit")
        if row["selected_ordinary"] != training["selected_ordinary"]:
            raise ValueError("Confirmation changed validation-only ordinary selection")
        if row["selected_ordinary"] not in protocol["ordinary_candidates"]:
            raise ValueError("Selected ordinary core was not preregistered")
        if seed in training_by_seed and training_by_seed[seed] != training:
            raise ValueError("The two domains do not share one frozen training identity")
        training_by_seed[seed] = training
        for key in OFFLINE_KEYS:
            _number(training[key], key, True)
        if not {"generic_hmm_common", "generic_hmm_final"} <= set(row["references"]):
            raise ValueError("Both mandatory generic HMM references are required")
        if not {"D_ce", "B_ce"} <= set(row["objective_controls"]) or "D_no_reset" not in row["ablations"]:
            raise ValueError("Missing preregistered objective/intervention controls")
        executions = [*row["arms"].values(), *row["references"].values(),
                      *row["objective_controls"].values(), *row["ablations"].values()]
        for item in executions:
            _execution(item, protocol["confirmation_episodes_per_domain"])
        for key in ("tape_hash", "planner_identity", "world_identity"):
            if len({item[key] for item in executions}) != 1:
                raise ValueError("Execution arms/references do not share " + key)
        if row["arms"]["D"]["planner_identity"] != training["common_planner_identity"]:
            raise ValueError("Confirmation changed the frozen common planner")
        if row["arms"]["D"]["world_identity"] != training["world_identity"]:
            raise ValueError("Confirmation changed the registered task world")
        equivalence = row["final_hmm_equivalence"]
        for key in ("actions_equal", "utility_equal"):
            if not isinstance(equivalence.get(key), bool):
                raise ValueError("Missing explicit final-model HMM equivalence outcome")
        left, right = row["arms"]["D"], row["references"]["generic_hmm_final"]
        actual_utility_equal = left["episode_values"] == right["episode_values"]
        if equivalence["utility_equal"] != actual_utility_equal:
            raise ValueError("Final-HMM utility equivalence conflicts with raw evidence")
        if "records" in left and "records" in right:
            actions_equal = ([r["trace"] for r in left["records"]]
                             == [r["trace"] for r in right["records"]])
            if actions_equal != equivalence["actions_equal"]:
                raise ValueError("Final-HMM action equivalence conflicts with retained traces")
        indexed[domain][seed] = row
    if any(set(group) != set(seeds) for group in indexed.values()):
        raise ValueError("An independent fitted seed is missing from a domain")
    return indexed, training_by_seed


def _online(item):
    costs = item["costs"]
    return sum(costs.get(key, 0.) for key in ("planner_construction_cpu_seconds",
               "inference_cpu_seconds", "control_cpu_seconds", "model_preparation_cpu_seconds")) / item["count"]


def _costs(ordered, seeds):
    per_seed = []
    for seed, row in zip(seeds, ordered):
        training = row["training"]
        common = training["preparation_cpu_seconds"] + training["common_calibration_cpu_seconds"]
        arms = {}
        for arm, item in row["arms"].items():
            candidate = ("ordinary_candidate_and_selection_cpu_seconds" if arm in ("A", "B")
                         else "hx_candidate_and_validation_cpu_seconds")
            offline = common + training[candidate] + row["owner_setup_cpu_seconds"]
            direct = item["costs"]["cpu_seconds"] / item["count"]
            arms[arm] = dict(online_cpu_per_episode=_online(item), execution_cpu_per_episode=direct,
                             shared_preparation_and_calibration_cpu_seconds=common,
                             candidate_and_selection_cpu_seconds=training[candidate],
                             simulation_owner_setup_cpu_seconds=row["owner_setup_cpu_seconds"],
                             offline_method_cpu_seconds=offline,
                             full_cpu_per_episode={str(n): offline / n + direct for n in REUSES})
        per_seed.append(dict(seed=int(seed), arms=arms))
    means = {arm: {key: float(np.mean([r["arms"][arm][key] for r in per_seed]))
                   for key in ("online_cpu_per_episode", "execution_cpu_per_episode", "offline_method_cpu_seconds")}
             for arm in ARMS}
    full = {str(n): {arm: float(np.mean([r["arms"][arm]["full_cpu_per_episode"][str(n)]
                                       for r in per_seed])) for arm in ARMS} for n in REUSES}
    ratio = lambda d, b: None if b <= 0 else float(d / b)
    return dict(unit="measured host process CPU seconds per episode/use",
                ratio_aggregation="ratio of arm means across eight fitted seeds; not mean of ratios",
                arm_means=means, full_arm_means_by_reuse=full,
                D_over_B=dict(online=ratio(means["D"]["online_cpu_per_episode"], means["B"]["online_cpu_per_episode"]),
                              execution=ratio(means["D"]["execution_cpu_per_episode"], means["B"]["execution_cpu_per_episode"]),
                              full_by_reuse={n: ratio(value["D"], value["B"]) for n, value in full.items()}),
                per_seed=per_seed,
                online_scope="Estimator plus controller and measured construction/preparation; no simulator owner.",
                full_scope="Shared prep/calibration, all method candidates/selection and simulated-owner setup amortized by reuse, plus entire measured research execution including simulated owner and trace handling. Not a native deployment cost.")


def summarize(rows, protocol=None):
    """Require the full frozen 8x2 cohort; infer only over independent fit means."""
    if protocol is None:
        protocol = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
    rows = list(rows)
    indexed, training = _indexed(rows, protocol)
    seeds = list(protocol["fit_seeds"])
    domains, raw_p = {}, {}
    for domain in DOMAINS:
        ordered = [indexed[domain][seed] for seed in seeds]
        arrays = {metric: {arm: np.array([row["arms"][arm]["mean"][metric] for row in ordered])
                           for arm in ARMS} for metric in METRICS}
        summaries = {}
        for metric in ("utility", "reward"):
            x = arrays[metric]
            effects = {"B-A": x["B"] - x["A"], "D-C": x["D"] - x["C"],
                       "C-A": x["C"] - x["A"], "D-B": x["D"] - x["B"]}
            effects["interaction"] = effects["D-C"] - effects["B-A"]
            summaries[metric] = {name: paired_summary(values, seeds) for name, values in effects.items()}
        raw_p[domain] = exact_sign_flip(arrays["utility"]["D"] - arrays["utility"]["B"])
        secondary = {}
        for name, arm, container, key in (("D-D_no_reset", "D", "ablations", "D_no_reset"),
                                         ("D-D_ce", "D", "objective_controls", "D_ce"),
                                         ("B-B_ce", "B", "objective_controls", "B_ce")):
            secondary[name] = {metric: paired_summary(
                arrays[metric][arm] - np.array([row[container][key]["mean"][metric] for row in ordered]), seeds)
                for metric in ("utility", "reward")}
        cost = _costs(ordered, seeds)
        lower = {metric: summaries[metric]["D-B"]["t_95pct_ci"][0] for metric in ("utility", "reward")}
        noninferior = all(value > -protocol["quality_noninferiority_margin"] for value in lower.values())
        online_ratio, full_ratio = cost["D_over_B"]["online"], cost["D_over_B"]["full_by_reuse"]["1000"]
        cheaper = all(value is not None and value <= protocol["cost_ratio_maximum"] for value in (online_ratio, full_ratio))
        reference_names = set(ordered[0]["references"])
        if any(set(row["references"]) != reference_names for row in ordered):
            raise ValueError("Optional candidate references are incomplete across fitted seeds")
        references = {name: dict(
            utility=paired_summary([row["references"][name]["mean"]["utility"] for row in ordered], seeds),
            D_minus_reference=paired_summary([row["arms"]["D"]["mean"]["utility"]
                                             - row["references"][name]["mean"]["utility"] for row in ordered], seeds),
            online_cpu_per_episode_mean=float(np.mean([_online(row["references"][name]) for row in ordered])))
            for name in sorted(reference_names)}
        domains[domain] = dict(
            arm_means={arm: {metric: float(arrays[metric][arm].mean()) for metric in METRICS} for arm in ARMS},
            contrasts=summaries["utility"], reward_contrasts=summaries["reward"], descriptive_secondary=secondary,
            references=references, costs=cost,
            primary_test=dict(contrast="D-B utility", raw_p=raw_p[domain], test="two-sided exhaustive paired sign flip", signs=256),
            cost_acceptance=dict(utility_and_reward_lower_bounds=lower,
                                 one_sided_confidence_per_endpoint=.975,
                                 simultaneous_scope="Bonferroni 95% for utility/reward within each domain; both domains must pass. No claim of 95% joint coverage of all four intervals.",
                                 noninferiority_margin=protocol["quality_noninferiority_margin"],
                                 cpu_ratio_maximum=protocol["cost_ratio_maximum"], full_cost_admission_reuse=1000,
                                 both_endpoints_noninferior=bool(noninferior), online_and_full_cpu_acceptable=bool(cheaper),
                                 accepted=bool(noninferior and cheaper)),
            final_hmm_equivalence={key: all(row["final_hmm_equivalence"][key] for row in ordered)
                                   for key in ("actions_equal", "utility_equal")})
    adjusted = holm_adjust(raw_p)
    for domain, result in domains.items():
        primary = result["contrasts"]["D-B"]
        result["primary_test"].update(holm_adjusted_p=adjusted[domain], family="IID/OOD primary D-B",
                                     minimum_mean_improvement=.01, interval_lower_must_exceed=0., alpha=.05,
                                     accepted=bool(primary["mean"] >= .01 and primary["t_95pct_ci"][0] > 0 and adjusted[domain] < .05))
    ledger = {key: float(sum(training[seed][key] for seed in seeds)) for key in OFFLINE_KEYS}
    allocated = sum(ledger[key] for key in OFFLINE_KEYS if key != "total_process_cpu_seconds")
    ledger["unallocated_measured_overhead_cpu_seconds"] = ledger["total_process_cpu_seconds"] - allocated
    if ledger["unallocated_measured_overhead_cpu_seconds"] < -1e-7:
        raise ValueError("Training component charges exceed measured total; possible double counting")
    equivalent = all(all(result["final_hmm_equivalence"].values()) for result in domains.values())
    return dict(
        schema="hcsn-r14-eight-fit-statistics-and-cost-v1", fit_seeds=seeds,
        source_commit=rows[0]["source_commit"], freeze_commit=rows[0]["freeze_commit"],
        freeze_sha256=rows[0]["freeze_sha256"],
        independent_unit="paired fitted seed, n=8 per domain; episodes and time steps are not independent replicates",
        interaction_definition="(D-C)-(B-A)", domains=domains,
        acceptance=dict(quality_gain=all(d["primary_test"]["accepted"] for d in domains.values()),
                        quality_guarded_research_cpu_saving=all(d["cost_acceptance"]["accepted"] for d in domains.values()),
                        positive_B_minus_A_is_not_primary_acceptance=True),
        training_cost_ledger=ledger,
        measured_confirmation_cpu_seconds=float(sum(row["total_process_cpu_seconds"] for row in rows)),
        measured_training_plus_confirmation_cpu_seconds=float(ledger["total_process_cpu_seconds"]
                                                               + sum(row["total_process_cpu_seconds"] for row in rows)),
        training_cost_note="Training totals are summed once per seed, not once per domain. Actual CE-only branch CPU is already inside total_process_cpu_seconds; its line is a disclosure, not an added charge. Shared warm computation is counted once in actual research cost.",
        selected_ordinary_per_seed=[dict(seed=seed, selected=training[seed]["selected_ordinary"]) for seed in seeds],
        identical_final_matrix_hmm=equivalent, HX_exclusive_mechanism_claim_supported=False,
        HX_exclusive_efficiency_claim_supported=False,
        equivalence_scope="An equal final-model matrix HMM forbids an HX-exclusive mechanism or efficiency inference; references use the same planner and raw histories.",
        inference_limits="Sign-flip tests assume exchangeable effect signs under the null; t intervals use fit means and seven degrees of freedom. Secondary effects are descriptive and do not replace or rescue the frozen primary test.",
        task_scope="Synthetic 40-state phase/bit/sensor CTMC. OOD changes irregular intervals only. Clean/unrepairable/high-fee witnesses are development checks, not extra confirmation domains.",
        deployment_economy_admitted=False, full_financial_fp32_admitted=False,
        production_rust_ownership_admitted=False, multilayer_semantic_or_long_term_memory_proved=False,
        production_activation=False,
        unmeasured_costs=["production communication", "recovery I/O", "GPU energy", "native Rust execution"],
        communication_scope="No communication occurs in this in-process synthetic task; this is not a measured zero-cost deployment claim.")


def load_and_summarize(run_dir, protocol=None):
    paths = sorted(Path(run_dir).glob("*/confirmation_*.json"))
    return summarize([json.loads(path.read_text()) for path in paths], protocol)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.run / "SUMMARY.json"
    result = load_and_summarize(args.run)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
