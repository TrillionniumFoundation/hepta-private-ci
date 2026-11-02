"""Fresh fixed-size confirmation, with separately reported risk, coverage, quality and utility gates."""

import argparse
import json
import os

import numpy as np

from experiments.hcsn_unknown_generator_r20_20261101.process_guard import outer
from .runner import STAT_COLUMNS, budget, resample, run_batches, stat_vector
from .study import ARM_MODELS, ROOT, archive, frozen, load_models, predictions, public, write
from .world import sample


def worker(panel, spec, calibration):
    output = ROOT / "confirmation_01" / panel
    output.mkdir(exist_ok=False)
    primary = calibration["primary"]
    policies = {arm:(arm, spec["threshold"]) for arm in spec["arms"]}
    for alias, base in spec["feasible_controls"].items():
        threshold = spec["threshold"] if calibration["qualifications"][base] else spec["fallback_threshold"]
        policies[alias] = (base, threshold)
    models = load_models()
    worlds = spec["confirmation_worlds"][panel]
    if worlds % spec["worlds_per_generator"]:
        raise ValueError("Whole generator clusters required")
    generators = worlds // spec["worlds_per_generator"]
    stats = {arm:np.zeros((generators, len(STAT_COLUMNS))) for arm in policies}
    invalid = dict.fromkeys(policies, 0)
    rows, archives = [], []
    for generator in range(generators):
        for index in range(spec["worlds_per_generator"]):
            world = sample("confirmation", panel, generator, index)
            values = predictions(world, models, policies)
            for arm, value in values.items():
                invalid[arm] += value["invalid"]
                stats[arm][generator] += stat_vector(value)
            rows.append(dict(stage="confirmation", panel=panel, generator=generator, index=index,
                public=public(world), target=world["target"], price=world["price"], predictions=values))
            if len(rows) == spec["archive_worlds"]:
                budget(spec)
                archives.append(archive(output, "worlds_%03d" % len(archives), rows))
                rows = []
    if rows:
        budget(spec)
        archives.append(archive(output, "worlds_%03d" % len(archives), rows))
    write(output / "ARCHIVES.json", archives)
    write(output / "CLUSTER_STATS_ARCHIVE.json", archive(output, "CLUSTER_STATS", dict(
        columns=STAT_COLUMNS, models={arm:value.tolist() for arm, value in stats.items()})))
    draws, paired, controls = resample(stats, primary, spec, worlds)
    write(output / "BOOTSTRAP_ARCHIVE.json", archive(output, "BOOTSTRAP", dict(
        columns=["fractional_risk", "overall_risk", "mean_utility", "before_brier", "fractional_rate", "answer_rate"],
        models={arm:value.tolist() for arm, value in draws.items()}, paired=paired.tolist(),
        paired_columns=["primary_minus_" + control + "_" + metric for control in controls
                        for metric in ("utility", "brier_improvement")])))
    result = dict(panel=panel, worlds=worlds, independent_generators=generators, primary=primary,
                  policies={}, comparisons={}, all_blockers_closed=False, full_model_adoption=False)
    for arm, (base, threshold) in policies.items():
        value = dict(attempts=worlds, invalid=invalid[arm], base_arm=base, threshold=threshold,
                     calibrated=calibration["qualifications"][base], forecast_law=ARM_MODELS[base][0], quality=None)
        if not invalid[arm]:
            total = stats[arm].sum(0)
            quality = dict(accepted=int(total[0]), errors=int(total[1]), fractional=int(total[2]), fractional_errors=int(total[3]),
                mean_utility=float(total[4] / worlds), before_brier=float(total[5] / worlds), support_losses=int(total[6]),
                reads=int(total[7]), fees=float(total[8]), mean_read_net_effect=float(total[9] / worlds),
                fractional_rate=float(total[2] / worlds), answer_rate=float(total[0] / worlds),
                upper95_fractional_risk=float(np.quantile(draws[arm][:, 0], .95)),
                upper95_overall_risk=float(np.quantile(draws[arm][:, 1], .95)))
            quality["risk_coverage_gate"] = bool(value["calibrated"] and not quality["support_losses"]
                and quality["fractional"] >= spec["minimum_fractional_count"]
                and quality["fractional_rate"] >= spec["minimum_fractional_rate"]
                and max(quality["upper95_fractional_risk"], quality["upper95_overall_risk"]) <= spec["risk_limit"])
            value["quality"] = quality
        result["policies"][arm] = value
    for column, control in enumerate(controls):
        if invalid[primary] or invalid[control]:
            result["comparisons"][control] = None
            continue
        difference = (stats[primary] - stats[control]).sum(0) / worlds
        result["comparisons"][control] = dict(utility_difference=float(difference[4]), brier_improvement=float(-difference[5]),
            utility_ci95=np.quantile(paired[:, 2 * column], [.025, .975]).tolist(),
            brier_ci95=np.quantile(paired[:, 2 * column + 1], [.025, .975]).tolist(),
            calibrated_control=calibration["qualifications"][policies[control][0]])
    def lower_nonnegative(name, field, strict=False):
        comparison = result["comparisons"].get(name)
        return comparison is not None and (comparison[field][0] > 0 if strict else comparison[field][0] >= 0)
    result["brier_nondegradation_gate"] = all(lower_nonnegative(name, "brier_ci95") for name in spec["primary_brier_controls"])
    result["paid_utility_gain_gate"] = all(lower_nonnegative(name, "utility_ci95", True) for name in spec["feasible_controls"])
    quality = result["policies"][primary]["quality"]
    result["bounded_content_contract_passed"] = bool(quality is not None and quality["risk_coverage_gate"]
        and result["brier_nondegradation_gate"] and result["paid_utility_gain_gate"])
    write(output / "SUMMARY.json", result)


def run(spec, calibration):
    output = ROOT / "confirmation_01"
    if not run_batches(__spec__.name, spec["confirmation_worlds"], output, spec):
        return 1
    panels = {name:json.loads((output / name / "SUMMARY.json").read_text()) for name in spec["confirmation_worlds"]}
    write(output / "SUMMARY.json", dict(primary=calibration["primary"], panels=panels,
        all_panels_bounded_content_contract_passed=all(value["bounded_content_contract_passed"] for value in panels.values()),
        all_blockers_closed=False, full_model_adoption=False, production_activation=False,
        scope="Finite ordinary reference; all5lawfamilies known from development/calibration; no analytic-core or open-domain attribution"))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("confirm", "reverse", "lag2", "relabeled_lag2", "lag2_skip"))
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    frozen("SOURCE_FREEZE.json", "SOURCE_PUBLICATION.json")
    frozen("POSTCALIBRATION_FREEZE.json", "CALIBRATION_PUBLICATION.json")
    spec = json.loads((ROOT / "protocol.json").read_text())
    calibration = json.loads((ROOT / "calibration_01/CALIBRATION.json").read_text())
    if calibration["primary"] is None:
        raise ValueError("No predeclared primary candidate qualified; confirmation remains unopened")
    if args.worker:
        cpu = spec["worker_cpus"][list(spec["confirmation_worlds"]).index(args.worker) % len(spec["worker_cpus"])]
        os.sched_setaffinity(0, {cpu})
        worker(args.worker, spec, calibration)
        return
    if args.child:
        raise SystemExit(run(spec, calibration))
    raise SystemExit(outer(__spec__.name, ROOT / "CONFIRMATION_PROCESS_RECEIPT.json", ROOT / "confirmation_01/WORKER_RECEIPTS.json"))


if __name__ == "__main__":
    main()
