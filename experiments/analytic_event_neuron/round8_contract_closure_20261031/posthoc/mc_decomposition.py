"""Retain each registered comparison's fit/configuration paired MC differences."""

from collections import defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics

from .independent_confirmation_audit import PRIMARY, SEEDS, STARTS, verify_frozen


def run(root):
    root = Path(root)
    output = root / "evidence/final_mc_decomposition.json"
    if output.exists():
        raise FileExistsError(output)
    freeze, exact = verify_frozen(root), {}
    arms = {arm for comparison in PRIMARY for arm in comparison}
    for arm in arms:
        mode, stage, _ = arm.split("/")
        for seed in SEEDS:
            fit = json.loads((root / f"evidence/calibration_{mode}_{seed}.json").read_text())
            for configuration, row in enumerate(fit["audits"][stage]["per_configuration"]):
                exact["nominal", seed, arm, configuration] = row["registered_return"]
    heldout = json.loads((root / "evidence/heldout_exact.json").read_text())
    for row in heldout["records"]:
        arm = f"{row['mode']}/{row['stage']}/hard"
        if arm in arms:
            for configuration, item in enumerate(row["configurations"]):
                exact["heldout", row["fit_seed"], arm, configuration] = item["registered_return"]
    values = {}
    with gzip.open(root / "evidence/confirmation_v1/trajectories.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            if row["arm"] in arms:
                values[row["regime"], row["fit_seed"], row["world_seed"], row["arm"]] = row["registered_return"]
    comparisons = []
    for regime in STARTS:
        for left, right in PRIMARY:
            fit_rows = []
            for fit_index, seed in enumerate(SEEDS):
                strata = defaultdict(list)
                for index in range(128):
                    world = STARTS[regime] + fit_index * 10000 + index
                    strata[index % 8].append({"world_seed": world,
                        "difference": values[regime, seed, world, left] - values[regime, seed, world, right]})
                details = []
                for configuration in range(8):
                    paired = [row["difference"] for row in strata[configuration]]
                    reference = exact[regime, seed, left, configuration] - exact[regime, seed, right, configuration]
                    variance = statistics.variance(paired) / len(paired)
                    details.append({"configuration_index": configuration, "worlds": strata[configuration],
                                    "MC_difference_mean": statistics.mean(paired), "exact_difference": reference,
                                    "variance_of_stratum_mean_estimate": variance,
                                    "MC_minus_exact": statistics.mean(paired) - reference})
                mc = statistics.mean(row["MC_difference_mean"] for row in details)
                target = statistics.mean(row["exact_difference"] for row in details)
                variance = sum(row["variance_of_stratum_mean_estimate"] for row in details) / 64
                fit_rows.append({"fit_seed": seed, "strata": details, "MC_difference": mc,
                                 "exact_difference": target, "MC_minus_exact": mc - target,
                                 "variance_of_fit_mean_estimate": variance,
                                 "conditional_MC_SE": math.sqrt(variance)})
            mc = statistics.mean(row["MC_difference"] for row in fit_rows)
            target = statistics.mean(row["exact_difference"] for row in fit_rows)
            variance = sum(row["variance_of_fit_mean_estimate"] for row in fit_rows) / 25
            observed_fit_variance = statistics.variance(row["MC_difference"] for row in fit_rows) / 5
            comparisons.append({"regime": regime, "left": left, "right": right,
                                "fits": fit_rows, "MC_difference": mc, "exact_difference": target,
                                "MC_minus_exact": mc - target, "conditional_stratified_MC_SE": math.sqrt(variance),
                                "realized_five_block_standard_error": math.sqrt(observed_fit_variance),
                                "residual_over_conditional_SE": (mc - target) / math.sqrt(variance) if variance else None})
    if verify_frozen(root) != freeze:
        raise AssertionError("frozen input changed during posthoc decomposition")
    report = {"schema": "round8-posthoc-mc-decomposition-v1", "freeze_sha256": freeze,
              "comparisons": comparisons, "fit_comparisons": 30, "configuration_comparisons": 240,
              "worlds_per_stratum": 16, "unique_worlds_per_regime": 640,
              "variance_formula": "For each fit: sum_c sample_variance(paired differences in c)/(16*8^2). Across five fixed fits: sum_fit variance/5^2.",
              "interpretation": "The frozen primary intervals are unchanged. Conditional Monte Carlo SE is an additional diagnostic; it excludes training-seed uncertainty and cannot prove absence of systematic bias.",
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with output.open("x", encoding="utf8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps([{key: row[key] for key in ("regime", "left", "right", "conditional_stratified_MC_SE", "realized_five_block_standard_error", "residual_over_conditional_SE")} for row in comparisons], indent=2))


if __name__ == "__main__":
    run(Path(__file__).resolve().parents[1])
