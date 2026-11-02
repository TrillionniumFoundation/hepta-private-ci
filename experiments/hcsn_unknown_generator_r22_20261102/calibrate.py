"""Prospective fixed-threshold seven-arm stratified risk and coverage calibration."""

import argparse
import json
import os

from scipy.stats import beta

from experiments.hcsn_unknown_generator_r20_20261101.process_guard import outer
from .runner import budget, run_batches
from .study import ROOT, accumulate, archive, counter, digest, frozen, load_models, predictions, public, write
from .world import sample


def upper(errors, count, delta):
    return 1. if not count or errors == count else float(beta.ppf(1 - delta, errors + 1, count - errors))


def worker(stratum, spec):
    output = ROOT / "calibration_01" / stratum
    output.mkdir(exist_ok=False)
    models = load_models()
    policies = {arm:(arm, spec["threshold"]) for arm in spec["arms"]}
    counts, rows, archives = {arm:counter() for arm in policies}, [], []
    for generator in range(spec["calibration_strata"][stratum]):
        world = sample("calibration", stratum, generator, 0)
        values = predictions(world, models, policies)
        for arm, value in values.items():
            accumulate(counts[arm], value)
        rows.append(dict(stage="calibration", stratum=stratum, generator=generator, index=0,
            public=public(world), target=world["target"], price=world["price"], predictions=values))
        if len(rows) == spec["archive_worlds"]:
            budget(spec)
            archives.append(archive(output, "worlds_%03d" % len(archives), rows))
            rows = []
    if rows:
        budget(spec)
        archives.append(archive(output, "worlds_%03d" % len(archives), rows))
    write(output / "COUNTS.json", counts)
    write(output / "ARCHIVES.json", archives)


def run(spec):
    output = ROOT / "calibration_01"
    if not run_batches(__spec__.name, spec["calibration_strata"], output, spec):
        return 1
    grid = {name:json.loads((output / name / "COUNTS.json").read_text()) for name in spec["calibration_strata"]}
    delta = spec["family_error_probability"] / (len(spec["arms"]) * len(grid) * 2)
    qualifications = {}
    for arm in spec["arms"]:
        for name, values in grid.items():
            entry = values[arm]
            if entry["worlds"] != spec["calibration_strata"][name]:
                raise ValueError("Fixed calibration population incomplete")
            entry["upper_error"] = upper(entry["errors"], entry["accepted"], delta)
            entry["upper_fractional_error"] = upper(entry["fractional_errors"], entry["fractional"], delta)
            entry["fractional_rate"] = entry["fractional"] / entry["worlds"]
            entry["population_quality_null"] = bool(entry["invalid"])
            entry["passed"] = bool(not entry["invalid"] and not entry["support_losses"]
                and max(entry["upper_error"], entry["upper_fractional_error"]) <= spec["risk_limit"]
                and entry["fractional"] >= spec["minimum_fractional_count"]
                and entry["fractional_rate"] >= spec["minimum_fractional_rate"])
        qualifications[arm] = all(values[arm]["passed"] for values in grid.values())
    primary = next((arm for arm in spec["primary_qualification_order"] if qualifications[arm]), None)
    write(output / "CALIBRATION.json", dict(schema="hcsn.r22.calibration.v1", grid=grid,
        simultaneous_delta=delta, bound_count=len(spec["arms"]) * len(grid) * 2,
        threshold=spec["threshold"], qualifications=qualifications, primary=primary,
        primary_selection_frozen_before_cases=True, fresh_confirmation_opened=False,
        brier_nondegradation_waived=False, all_blockers_closed=False))
    frozen("SOURCE_FREEZE.json", "SOURCE_PUBLICATION.json")
    paths = [ROOT / "development_fit_final/MODELS.json.gz", ROOT / "development_fit_final/FIT_IDENTITY.json",
             ROOT / "inputs/r20_models.json.gz", output / "CALIBRATION.json", output / "WORKER_RECEIPTS.json"]
    paths += [output / name / item for name in grid for item in ("COUNTS.json", "ARCHIVES.json")]
    write(ROOT / "POSTCALIBRATION_FREEZE.json", dict(schema="hcsn.r22.postcalibration.freeze.v1",
        files={str(path.relative_to(ROOT)):digest(path) for path in paths}, primary=primary,
        qualifications=qualifications, threshold=spec["threshold"], fresh_confirmation_opened=False))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("calibrate", "calibrate_reverse", "calibrate_lag2", "calibrate_relabeled_lag2", "calibrate_lag2_skip"))
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    frozen("SOURCE_FREEZE.json", "SOURCE_PUBLICATION.json")
    spec = json.loads((ROOT / "protocol.json").read_text())
    if args.worker:
        cpu = spec["worker_cpus"][list(spec["calibration_strata"]).index(args.worker) % len(spec["worker_cpus"])]
        os.sched_setaffinity(0, {cpu})
        worker(args.worker, spec)
        return
    if args.child:
        raise SystemExit(run(spec))
    raise SystemExit(outer(__spec__.name, ROOT / "CALIBRATION_PROCESS_RECEIPT.json", ROOT / "calibration_01/WORKER_RECEIPTS.json"))


if __name__ == "__main__":
    main()
