"""Planning arithmetic from retained TRAIN aggregates only; no data generation."""

import hashlib
import json
import math
from pathlib import Path
import statistics
import time

import scipy
from scipy.stats import chi2, norm, t


HERE = Path(__file__).resolve().parent
RUN = HERE.parents[1] / "runs/codex-cloud-ndu-training-train-d1"
ALPHA = 0.012  # .0005 of the .0125 claim allowance is reserved for MC error.
BLOCKS = 32
SEEDS_PER_BLOCK = 3
SOURCES = 768
WAVES = 4


def describe(values):
    values = list(values)
    mean, sd = statistics.mean(values), statistics.stdev(values)
    return {"values": values, "mean": mean, "sample_sd": sd,
            "illustrative_iid_normal_sd_ci95": [sd*math.sqrt(2/chi2.ppf(.975, 2)),
                                                 sd*math.sqrt(2/chi2.ppf(.025, 2))],
            "warning": "three seeds share one TRAIN set, diagnostic draws and budget block; this is not independent confirmation"}


if __name__ == "__main__":
    started = time.process_time()
    raw = (RUN / "result.json").read_bytes()
    r = json.loads(raw)
    report = {"source_result_sha256": hashlib.sha256(raw).hexdigest(),
              "statistical_tail_alpha": ALPHA, "claim_alpha_including_mc": .0125,
              "scope": "analytical planning sensitivity only; no new TRAIN/validation/formal inputs, models, predictions or confirmatory p-values",
              "scipy_version": scipy.__version__, "descriptive": {}, "sensitivity": []}
    for kind in ("iid", "stratified"):
        for metric in ("task_utility", "joint_success"):
            report["descriptive"][f"{kind}/{metric}"] = describe(
                row["final_N_minus_A"][metric] for row in r["contrasts"][kind])
        report["descriptive"][f"{kind}/cpu_net"] = describe(
            r["systems"]["N"]["candidates"][f"{kind}-{seed}"]["train_complete_cpu_net"] -
            r["systems"]["A"]["candidates"][f"{kind}-{seed}"]["train_complete_cpu_net"]
            for seed in (11, 23, 47))
    report["descriptive"]["sampler_by_objective_interaction"] = describe(
        ss["final_N_minus_A"]["task_utility"] - ii["final_N_minus_A"]["task_utility"]
        for ss, ii in zip(r["contrasts"]["stratified"], r["contrasts"]["iid"]))
    point_sd = report["descriptive"]["stratified/task_utility"]["sample_sd"]
    upper_sd = report["descriptive"]["stratified/task_utility"]["illustrative_iid_normal_sd_ci95"][1]
    for blocks in (16, 32, 64):
        critical = float(t.isf(ALPHA, blocks-1))
        for multiplier in (1, 2, 4, upper_sd/point_sd):
            for rho_within_block in (0.0, 0.5, 1.0):
                effective_seeds = 3*blocks/(1+2*rho_within_block)
                for source_sd in (0.0, .005, .01, .02):
                    se = math.sqrt((multiplier*point_sd)**2/effective_seeds + source_sd**2/SOURCES)
                    row = {"blocks": blocks, "training_seeds": 3*blocks,
                        "within_block_correlation_assumption": rho_within_block,
                        "effective_seeds_in_sensitivity_model": effective_seeds,
                        "seed_sd_multiplier_assumption": multiplier, "source_sd_assumption": source_sd,
                        "standard_error_model": se, "mde_marginal_80": (critical+norm.ppf(.8))*se,
                        "mde_six_superiority_80_union_bound_model": (critical+norm.ppf(1-.2/6))*se,
                        "power_marginal_normal_approx": {str(effect): float(norm.sf(critical-effect/se))
                            for effect in (.0005, .001, .002, .004)}}
                    report["sensitivity"].append(row)
    report["cpu_net_sensitivity"] = []
    for block_sd in (.003, .006, .01):
        se = math.sqrt(block_sd**2/BLOCKS + .01**2/SOURCES)
        report["cpu_net_sensitivity"].append({"block_sd_assumption_after_four_waves": block_sd,
            "source_sd_assumption": .01, "se": se,
            "mde_six_superiority_80_union_bound_model": float((t.isf(ALPHA, BLOCKS-1)+norm.ppf(1-.2/6))*se)})
    reference = r["systems"]["A"]["candidates"]["iid-11"]["service"]["cost"]["reference_full_work_units"]
    count = BLOCKS*3*4*WAVES*SOURCES*16
    service_cpu = [statistics.mean(row["service"]["per_row_cost"]["cpu_ns"])/1e9
        for system in r["systems"].values() for row in system["candidates"].values()]
    report["proposed_design"] = {"blocks": BLOCKS, "independent_training_seed_tuples": 3*BLOCKS,
        "models_per_system_per_block": 6, "sources": SOURCES, "source_cohorts_of_four": SOURCES//4,
        "formal_rows": SOURCES*16, "timing_waves": WAVES, "primary_service_outputs": count,
        "build_cpu_cap_each_system_total": BLOCKS*10, "build_cpu_cap_both_systems_total": 2*BLOCKS*10,
        "build_units_cap_both_systems_total": 2*BLOCKS*12_000_000_000,
        "formal_service_cpu_cap_each_system": 1800, "formal_service_cpu_cap_both_systems": 3600,
        "shared_statistical_and_manifest_cpu_cap": 300, "prospective_total_attributed_cpu_cap": 4540,
        "primary_service_units_at_existing_one_forward_profile": count*reference,
        "primary_service_units_upper_cap_two_full_equivalents": count*2*reference,
        "observed_d1_service_cpu_range_seconds_per_output": [min(service_cpu), max(service_cpu)],
        "linear_forecast_primary_service_cpu_range_only": [count*min(service_cpu), count*max(service_cpu)],
        "comparison_budget_note": "10s/12B is per original three-seed/two-candidate SYSTEM BLOCK, never per individual model"}
    report["source_uncertainty_gap"] = "retained TRAIN score aggregates cannot estimate physical-source or independent timing-block variance; sensitivity values are assumptions, not observations"
    report["planning_power_limit"] = "marginal power is not conjunction power; even the six-test union-bound model excludes retention/admission failures and depends on assumed variance and asymptotic inference"
    report["analysis_cpu_seconds_excluding_output_write"] = time.process_time()-started
    with (HERE / "power-plan-v2.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"descriptive": report["descriptive"], "proposed_design": report["proposed_design"],
                      "cpu_net_sensitivity": report["cpu_net_sensitivity"]}, indent=2))
