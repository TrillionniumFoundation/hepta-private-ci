"""Post-experiment descriptive reporting; not part of candidate selection."""
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact_io import read, save, sha


def main():
    run = ROOT / "execution_r1/run"
    result = read(run / "RESULTS.json")
    verified = read(ROOT / "independent_verification/VERIFIED.json")
    if not verified["all_checks_pass"] or verified["protocol_sha256"] != result["protocol_sha256"]:
        raise ValueError("complete independent verification required before report generation")
    protocol = read(ROOT / "PROTOCOL_FROZEN.json")
    fits = protocol["fits"]
    candidates = {fit: read(run / f"fit_{fit}_CANDIDATES.json.gz") for fit in fits}
    rows, selection, proxies = {}, {}, {}
    for fit, record in candidates.items():
        rows[str(fit)] = record["complete_train_rows"]
        selection[str(fit)] = {}
        for arm in ("E", "G", "EU", "EA"):
            path = record["paths"][arm]
            selection[str(fit)][arm] = dict(alpha=path["selected_alpha"],
                all_train_own_means=[p["mean_train_own_utility"] for p in path["candidates"]],
                selected_train_own_mean=path["candidates"][path["selected_index"]]["mean_train_own_utility"],
                endpoint_converged=record["solvers"][arm]["converged"],
                endpoint_FW_gap=record["solvers"][arm]["numerical_fw_gap"])
        # All selected weight arms measured under the same E quadratic from stored Gram statistics.
        problem = record["problems"]["E"]
        origin = np.asarray(problem["original"])
        matrices, rhs = np.asarray(problem["matrices"]), np.asarray(problem["rhs"])
        baseline = problem["C_diagnostics"]["weighted_target_loss"]
        proxies[str(fit)] = {}
        for arm in ("C", "E", "G", "EU", "EA", "M", "R"):
            delta = np.asarray(record["selected_heads"][arm])[:3] - origin
            difference = sum(float(d @ A @ d - 2 * b @ d) for d, A, b in zip(delta, matrices, rhs))
            penalty = 1e-4 * float(np.sum(delta ** 2))
            proxies[str(fit)][arm] = dict(common_E_objective=baseline + difference,
                                         common_E_weighted_target_loss=baseline + difference - penalty,
                                         delta_norm=float(np.linalg.norm(delta)))
    behavior = {}
    metrics = ("utility", "fees", "reads_requested", "reads_completed", "repairs", "elapsed", "correct", "submitted",
               "selected_q_rmse", "posterior_probability_mse", "teacher_regret_mean", "ranking_error_mean", "margin_absolute_error_mean")
    arms = tuple(result["summary"]["iid"])
    test_records = {(fit, domain): read(run / f"test_{fit}_{domain}_RESULTS.json.gz") for fit in fits for domain in ("iid", "ood")}
    for domain in ("iid", "ood"):
        behavior[domain] = {arm: {metric: float(np.mean([np.mean([row["arms"][arm][metric]
            for row in test_records[fit, domain]["records"]]) for fit in fits])) for metric in metrics} for arm in arms}
    transfer = {}
    for fit in fits:
        if not result["gates"][str(fit)]["E"]["accepted"]:
            continue
        transfer[str(fit)] = {}
        for split in ("validation", "test"):
            transfer[str(fit)][split] = {}
            for domain in ("iid", "ood"):
                records = read(run / f"{split}_{fit}_{domain}_RESULTS.json.gz")["records"]
                delta = {metric: float(np.mean([row["arms"]["E"][metric] - row["arms"]["C"][metric]
                                               for row in records])) for metric in metrics[:8]}
                values = np.asarray([row["arms"]["E"]["utility"] - row["arms"]["C"]["utility"] for row in records])
                reward = 2 * delta["correct"] - delta["submitted"]
                if abs(reward - delta["fees"] - delta["utility"]) > 2e-13:
                    raise ArithmeticError("utility reward/fee identity failed")
                transfer[str(fit)][split][domain] = dict(world_count=len(records), differences=delta,
                    reward_difference=reward, fee_saving=-delta["fees"],
                    positive_world_differences=int(np.count_nonzero(values > 0)),
                    zero_world_differences=int(np.count_nonzero(values == 0)),
                    negative_world_differences=int(np.count_nonzero(values < 0)),
                    minimum_world_difference=float(values.min()), maximum_world_difference=float(values.max()),
                    interpretation="Post-hoc descriptive decomposition of fixed records; exact expectation within each world, variation over sampled public worlds; no new candidate or causal mechanism identification.")
    phase_costs = {}
    for phase in ("preparation", "semantic_checks", "protocol_freeze", "execution_r1", "independent_verification",
                  "posthoc/freeze_receipt", "posthoc/execution_r1"):
        receipt = read(ROOT / phase / "PROCESS_RECEIPT.json")
        phase_costs[phase] = {key: receipt[key] for key in ("exit_code", "child_total_cpu_seconds",
            "elapsed_wall_seconds", "child_peak_rss_bytes", "controller_cpu_seconds")}
    solver_costs = {arm: sum(candidates[fit]["solvers"][arm]["cpu_seconds"] for fit in fits) for arm in ("E", "G", "EU", "EA")}
    path_costs = {arm: sum(candidates[fit]["paths"][arm]["inclusive_path_cpu_seconds"] for fit in fits) for arm in ("E", "G", "EU", "EA")}
    shared_preparation = sum(candidates[fit]["shared_input_state_feature_own_teacher_cpu_seconds"] for fit in fits)
    E_setup = sum(candidates[fit]["problems"]["E"]["setup_cpu_seconds"] for fit in fits)
    construction = {arm: shared_preparation + E_setup + solver_costs[arm] + path_costs[arm] +
        sum(candidates[fit]["models"][arm]["serialize_save_load_cpu_seconds"] for fit in fits) for arm in ("E", "G")}
    holdout_policy = {arm: 0. for arm in arms}
    J_cold = 0.
    evaluator_cpu = 0.
    for split in ("validation", "test"):
        for fit in fits:
            for domain in ("iid", "ood"):
                for row in read(run / f"{split}_{fit}_{domain}_RESULTS.json.gz")["records"]:
                    J_cold += row["own_bellman"]["full_cold_preparation_cpu_seconds"]
                    for arm, values in row["arms"].items():
                        holdout_policy[arm] += values["policy_cpu_seconds"] + values["arm_initialization_cpu_seconds"]
                        evaluator_cpu += values["cpu_seconds"]
    cost = dict(measured_phase_receipts=phase_costs,
        measured_child_cpu_sum_before_reporting_seconds=sum(x["child_total_cpu_seconds"] for x in phase_costs.values()),
        worker_complete_child_cpu_seconds=phase_costs["execution_r1"]["child_total_cpu_seconds"],
        shared_TRAIN_input_state_feature_own_teacher_cpu_seconds=shared_preparation,
        E_G_shared_Gram_setup_cpu_seconds=E_setup,
        solver_cpu_seconds=solver_costs, finite_path_cpu_seconds=path_costs,
        matched_candidate_construction_cpu_seconds=construction,
        matched_candidate_construction_G_over_E_ratio=construction["G"] / construction["E"],
        candidate_construction_scope="Common full TRAIN preparation + common E Gram setup + endpoint method + own finite path + selected model serialization. This excludes other experimental arms, source bookkeeping and all held-out evaluation; it is not an end-to-end training speedup.",
        TRAIN_all_control_scoring_cpu_seconds=sum(candidates[fit]["other_TRAIN_control_cpu_seconds"] for fit in fits),
        holdout_J_full_cold_planning_cpu_seconds=J_cold,
        heldout_policy_decision_and_initialization_cpu_seconds=holdout_policy,
        heldout_evaluator_cpu_seconds=evaluator_cpu,
        policy_timing_scope="Measured Python decision blocks, each arm/world has cold features; J planning above is additional, and evaluator timings also include shared truth diagnostics. Not production latency or an equal-hardware neural-throughput benchmark.",
        no_addition_of_nested_component_times_to_process_total=True,
        excluded_unknown_costs=["Base-model training", "Unrecovered earlier searches", "Agent/editor and external tool orchestration", "Controller startup imports/final receipt writes", "Energy and economic CPU-to-utility conversion"],
        full_research_economic_net_value_qualified=False)
    diagnostic = read(ROOT / "posthoc/execution_r1/run/RESULTS.json")
    report = dict(protocol_sha256=result["protocol_sha256"], independently_verified=True,
        weight_efficacy_qualified=result["weight_efficacy_qualified"], primary=result["primary"],
        summary=result["summary"], gates=result["gates"], full_train_state_rows=rows,
        total_complete_train_rows=sum(rows.values()), selected_paths=selection,
        accepted_E_validation_to_TEST_transfer=transfer,
        common_E_proxy_from_Gram_identity=proxies, proxy_scope="Descriptive F64 quadratic identity, not an independent exact loss certificate",
        behavior=behavior, visitation_scope="Every arm's task/diagnostic metrics are under its own policy visitation distribution; differences do not isolate same-state calibration.",
        costs=cost, verification=verified, posthoc_diagnostic=diagnostic)
    save(ROOT / "reporting/DERIVED_REPORT.json", report)
    save(ROOT / "reporting/COSTS.json", cost)
    lines = ["# Frozen single-run results", "", f"Pure-weight efficacy qualified: **{result['weight_efficacy_qualified']}**.", "",
        "These are conditional results for five existing fits of the finite deadline-six sign task. There are no new base-training fits and no live Trader or full NDU economic claim.", "",
        "## TEST utility", "", "| Arm | IID | OOD | IID delta vs C | OOD delta vs C |", "| --- | ---: | ---: | ---: | ---: |"]
    for arm in ("C", "E", "G", "EU", "EA", "M", "R", "P", "J", "E_gated", "G_gated"):
        a, b = result["summary"]["iid"][arm], result["summary"]["ood"][arm]
        lines.append(f"| {arm} | {a['mean']:.10f} | {b['mean']:.10f} | {a['delta']:+.10f} | {b['delta']:+.10f} |")
    lines += ["", "## Primary conditional comparisons", "", "| Comparison | Delta | Bonferroni-two 95% conditional interval | Lower bound > .005 |", "| --- | ---: | --- | --- |"]
    for name, entry in result["primary"].items():
        lo, hi = entry["familywise_95_conditional_interval"]
        lines.append(f"| {name} | {entry['delta']:+.10f} | [{lo:.10f}, {hi:.10f}] | {entry['benefit_pass']} |")
    lines += ["", "## Frozen alpha selection and validation", "", "| Fit | E alpha | G alpha | EU alpha | EA alpha | E accepted | G accepted |", "| --- | ---: | ---: | ---: | ---: | --- | --- |"]
    for fit in fits:
        selected, gates = selection[str(fit)], result["gates"][str(fit)]
        lines.append(f"| {fit} | {selected['E']['alpha']} | {selected['G']['alpha']} | {selected['EU']['alpha']} | {selected['EA']['alpha']} | {gates['E']['accepted']} | {gates['G']['accepted']} |")
    lines += ["", "## Why a validation acceptance is not a task-value guarantee", "",
        "The acceptance rule is a threshold on finite validation means, not a confidence bound or a calibrated false-positive-rate guarantee. Every world is evaluated by full expectation; the remaining validation/TEST variability is over public-world samples. The test outcome does not justify changing the gate or retrospectively selecting another raw arm.", ""]
    for fit, splits in transfer.items():
        val, test = splits["validation"]["ood"], splits["test"]["ood"]
        lines += [f"For accepted E fit {fit}, OOD validation gain was {val['differences']['utility']:+.10f}; OOD TEST gain was {test['differences']['utility']:+.10f}. The accepted model's TEST expected reward changed by {test['reward_difference']:+.10f}, while fee savings contributed {test['fee_saving']:+.10f}. The reward loss exceeds the fee saving.", "",
            f"The {val['world_count']} OOD validation worlds contained {val['positive_world_differences']} positive / {val['zero_world_differences']} zero / {val['negative_world_differences']} negative paired differences; the {test['world_count']} OOD TEST worlds contained {test['positive_world_differences']} positive / {test['zero_world_differences']} zero / {test['negative_world_differences']} negative differences. These counts describe scenario heterogeneity, not additional independently trained fits, and do not estimate a general gate false-positive rate.", ""]
    lines += ["", "## Measured process cost", "", "| Phase | Child CPU seconds | Wall seconds | Peak RSS bytes |", "| --- | ---: | ---: | ---: |"]
    for name, entry in phase_costs.items():
        lines.append(f"| {name} | {entry['child_total_cpu_seconds']:.6f} | {entry['elapsed_wall_seconds']:.6f} | {entry['child_peak_rss_bytes']} |")
    lines += ["", f"Measured child CPU sum before this reporting process: {cost['measured_child_cpu_sum_before_reporting_seconds']:.6f} seconds. Nested component costs must not be added again.", "",
        f"E/G endpoint solver CPU: {solver_costs['E']:.6f} / {solver_costs['G']:.6f} seconds. The matched candidate-construction figures including their common preparation are {construction['E']:.6f} / {construction['G']:.6f} seconds, ratio {construction['G']/construction['E']:.6f}. These are restricted construction figures, not full-training speedup.", "",
        f"Cold own-law Bellman preparation for the 480 held-out worlds cost {J_cold:.6f} CPU seconds, in addition to J policy lookup/initialization. P/J gains are program gains, never pure-weight gains.", "",
        "Full historical/editor/agent/controller-startup/energy/economic costs remain unknown where unmeasured. Complete worker and verification receipts remain the authoritative measured process totals.", "",
        "## Independent execution", "",
        f"All {verified['stored_finite_path_candidates_verified']} stored path heads and all schedule/selection/gate/rollback/statistical records passed. TRAIN replay: {verified['train_replay']['world_candidate_pairs']} world/path pairs, maximum absolute utility difference {verified['train_replay']['maximum_absolute_utility_difference']}. Held-out replay: {verified['holdout_replay']['world_arm_pairs']} world/arm pairs, maximum absolute eight-metric difference {verified['holdout_replay']['maximum_absolute_behavior_difference']}, node difference {verified['holdout_replay']['maximum_visited_node_difference']}.", "",
        "The verifier uses the original recursive TRAIN executor and a separate held-out literal-head evaluator. It shares the original fixed simulator/core/law definitions and does not count as new statistical evidence.", ""]
    lines += ["## Separate post-hoc diagnosis", "",
        "A separately frozen, approved read-only diagnostic covers all 16 validation and 32 TEST OOD worlds for accepted E fit23. It changes no weights, sample, seed, gate or primary inference. The complete source, input identities, 48 per-world records and process receipt are under `posthoc/`.", "",
        "| Existing split | Own-law E minus C | Evaluator E minus C | Evaluator contribution from own-target violations | Other contribution |", "| --- | ---: | ---: | ---: | ---: |"]
    for split, entry in diagnostic["summary"].items():
        cats = entry["categories"]
        lines.append(f"| {split} | {entry['mean_own_E_minus_C']:+.10f} | {entry['mean_evaluator_E_minus_C']:+.10f} | {cats['own_target_violation']['evaluator_advantage_contribution']:+.10f} | {cats['other']['evaluator_advantage_contribution']:+.10f} |")
    lines += ["", "The TEST loss also occurs under the checkpoint's own law. On these exposed worlds, the failure therefore cannot be explained solely by the difference between the checkpoint law and the evaluator law. The edited head chooses some actions whose own-law one-step advantage over C is negative. This identifies head/target inconsistency on these states; it does not prove a general capacity impossibility or a universal law-error absence.", "",
        "For each law the diagnostic verifies the unnormalized E-occupancy performance-difference identity, and separately verifies the first-common-prefix partition using complete edited-policy suffix values. Local one-step follow-C counterfactuals are never substituted for those complete suffix values. Coordinate-wise delta-weight times hidden contributions are fixed-representation linear accounting, not independent causal interventions on individual weights.", "",
        f"Maximum stored utility discrepancy: {diagnostic['identity_checks']['max_frozen_record_utility_error']}; own/evaluator performance-difference residuals: {diagnostic['identity_checks']['max_own_performance_difference_residual']} / {diagnostic['identity_checks']['max_evaluator_performance_difference_residual']}; first-prefix partition residual: {diagnostic['identity_checks']['max_first_divergence_partition_residual']}; linear-head margin residual: {diagnostic['identity_checks']['max_linear_head_margin_residual']}.", "",
        f"The predeclared post-hoc illustration rule selects TEST index {diagnostic['example']['test_index']}, with E-minus-C {diagnostic['example']['evaluator_E_minus_C']:.10f}. Full records remain available, and this worst example is not new confirmation.", ""]
    with (ROOT / "reporting/REPORT.md").open("x") as stream:
        stream.write("\n".join(lines))
    print(json.dumps(dict(report="reporting/DERIVED_REPORT.json", weight_efficacy_qualified=result["weight_efficacy_qualified"],
                          primary=result["primary"], measured_child_cpu_seconds=cost["measured_child_cpu_sum_before_reporting_seconds"]), sort_keys=True))


if __name__ == "__main__":
    main()
