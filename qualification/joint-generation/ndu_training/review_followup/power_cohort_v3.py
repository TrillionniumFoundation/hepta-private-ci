"""Corrected block/cohort sensitivity; no new input, inference or training."""

import hashlib
import json
import math
from pathlib import Path

from scipy.stats import norm, t

HERE = Path(__file__).resolve().parent
BLOCKS, COHORTS, TUPLES = 32, 192, 3
CRITICAL = float(t.isf(.012, BLOCKS-1))


def scenario(label, block_sd, cohort_sd, interaction_sd):
    se = math.sqrt(block_sd**2/BLOCKS + cohort_sd**2/COHORTS
                   + interaction_sd**2/(BLOCKS*COHORTS))
    return {"label": label, "block_sd_assumption": block_sd,
            "cohort_sd_assumption": cohort_sd, "interaction_sd_assumption": interaction_sd,
            "se_model": se, "mde_marginal80": float((CRITICAL+norm.ppf(.8))*se),
            "mde_six80_union_model": float((CRITICAL+norm.ppf(1-.2/6))*se)}


if __name__ == "__main__":
    old_bytes = (HERE / "power-plan-v2.json").read_bytes()
    old = json.loads(old_bytes)
    sd = old["descriptive"]["stratified/task_utility"]["sample_sd"]
    raw = []
    for multiplier, corr, cohort_sd, interaction_sd in (
            (2, .5, .005, 0), (4, 1., .005, 0),
            (2, .5, .01, .01), (4, 1., .01, .02)):
        # An assumption linking individual seed SD to a three-tuple block mean,
        # not an estimate from the single existing block.
        block_sd = multiplier*sd*math.sqrt((1+2*corr)/TUPLES)
        row = scenario("raw utility illustrative only", block_sd, cohort_sd, interaction_sd)
        row.update(seed_sd_multiplier_assumption=multiplier, within_block_corr_assumption=corr)
        raw.append(row)
    cpu = [scenario("CPU-net illustrative only", block_sd, cohort_sd, interaction_sd)
           for block_sd, cohort_sd, interaction_sd in (
               (.003, .005, 0), (.003, .01, 0), (.006, .01, 0),
               (.01, .01, 0), (.006, .01, .02), (.006, .02, .02))]
    report = {"scope": "NDU A/N proposal only; analytical assumptions, no experiment",
        "previous_v2_sha256": hashlib.sha256(old_bytes).hexdigest(),
        "estimand_unit": "random three-tuple complete-budget block; fixed TRAIN and host",
        "blocks": BLOCKS, "tuples_per_block": TUPLES, "training_tuples": BLOCKS*TUPLES,
        "physical_sources": 768, "shared_timing_cohorts": COHORTS,
        "formula": "SE^2=sigma_block^2/32+sigma_cohort^2/192+sigma_interaction^2/(32*192)",
        "source_to_cohort_warning": "sigma_cohort=sigma_source/2 requires independent within-cohort source effects; not assumed for shared CPU timers",
        "raw_sensitivity": raw, "cpu_net_sensitivity": cpu,
        "power_warning": "six-test model MDE is not calibrated conjunction power; t cutoff and MC quantile bounds do not establish test size",
        "budget": {"scope": "this NDU A/N design, excludes content and dynamic research",
            "build_attributed_cpu_each_system": 320, "service_cpu_each_system": 1800,
            "statistics_physical_cpu_cap": 300, "statistics_fully_attributed_each_system": 300,
            "paired_attributed_cpu_cap": 4840, "physical_cpu_upper_cap": 4540,
            "model_service_units_cap": 1500000000000},
        "new_training_or_predictions": False}
    with (HERE / "power-plan-v3.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, indent=2))
