"""Prospective fixed-threshold calibration-power study; original failure immutable."""

import argparse
import gzip
import json

from .campaign import ROOT, archive, digest, frozen, predictions, public, upper, write
from .process_guard import outer, persist, workers
from .world_v2 import sample


def worker(stratum, spec):
    output = ROOT / "calibration_v2_01" / stratum
    output.mkdir(exist_ok=False)
    models = json.loads(gzip.decompress((ROOT / "prepare_01/MODELS.json.gz").read_bytes()))
    cutoffs = json.loads((ROOT / "prepare_01/OOD.json").read_text())["cutoffs"]
    thresholds = {name:[spec["threshold"]] for name in models}
    counts = {name:dict(accepted=0, errors=0, fractional=0, fractional_errors=0, invalid=0,
                       payoff_sum=0., before_brier_sum=0., actual_reads=0) for name in models}
    rows, archives = [], []
    for generator in range(spec["calibration_strata"][stratum]):
        world = sample(stratum, generator, 0)
        values = predictions(world, models, cutoffs, thresholds)
        rows.append(dict(phase="r20_calibration_power_v2", stratum=stratum, generator=generator,
            public=public(world), target=world["target"], price=world["price"], predictions=values))
        for name, candidates in values.items():
            value, count = next(iter(candidates.values())), counts[name]
            count["invalid"] += value["invalid"]
            if not value["invalid"]:
                a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
                for key, amount in zip(("accepted", "errors", "fractional", "fractional_errors"),
                                      (a, a and e, f, f and e), strict=True):
                    count[key] += amount
                count["payoff_sum"] += value["payoff"]
                count["before_brier_sum"] += value["before_brier"]
                count["actual_reads"] += value["read_index"] is not None
        if len(rows) == spec["archive_worlds"]:
            archives.append(archive(output, "worlds_%03d" % len(archives), rows))
            rows = []
    if rows:
        archives.append(archive(output, "worlds_%03d" % len(archives), rows))
    write(output / "COUNTS.json", counts)
    write(output / "ARCHIVES.json", archives)


def run(spec):
    output = ROOT / "calibration_v2_01"
    receipts, launch_errors = workers(__spec__.name, spec["calibration_strata"], output)
    if launch_errors or any(receipt["exit_code"] for receipt in receipts.values()):
        persist(output / "FAILED.json", dict(calibration_qualified=False, reason="Worker failure; no complete-population estimate"))
        return 1
    grid = {stratum:json.loads((output / stratum / "COUNTS.json").read_text()) for stratum in spec["calibration_strata"]}
    delta = spec["family_error_probability"] / (len(spec["models"]) * len(grid) * 2)
    selected = {}
    for name in spec["models"]:
        for stratum in grid:
            entry = grid[stratum][name]
            entry["upper_error"] = upper(entry["errors"], entry["accepted"], delta)
            entry["upper_fractional_error"] = upper(entry["fractional_errors"], entry["fractional"], delta)
            entry["passed"] = bool(not entry["invalid"] and entry["upper_error"] <= spec["risk_limit"]
                and entry["upper_fractional_error"] <= spec["risk_limit"]
                and entry["fractional"] >= spec["minimum_fractional_answers"])
        selected[name] = dict(threshold=spec["threshold"],
            calibration_gate_passed=all(grid[stratum][name]["passed"] for stratum in grid))
    write(output / "CALIBRATION.json", dict(schema="hcsn.r20.power-calibration.v2", grid=grid, selected=selected,
        simultaneous_delta=delta, original_r20_54_bound_gate="FAILED; unchanged; not pooled",
        confirmation_opened=False))
    frozen("CALIBRATION_V2_SOURCE_FREEZE.json", "CALIBRATION_V2_SOURCE_PUBLICATION.json")
    bound = [ROOT / "prepare_01/MODELS.json.gz", ROOT / "prepare_01/OOD.json", output / "CALIBRATION.json",
             output / "WORKER_RECEIPTS.json"]
    bound += [output / stratum / name for stratum in grid for name in ("ARCHIVES.json", "COUNTS.json")]
    write(ROOT / "POSTCALIBRATION_V2_FREEZE.json", dict(schema="hcsn.r20.postcalibration.v2.freeze.v1",
        files={str(path.relative_to(ROOT)):digest(path) for path in bound}, original_r20_holdouts_opened=False,
        new_confirmation_opened=False, selected=selected))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("calibrate", "calibrate_reverse", "calibrate_lag2"))
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    frozen("CALIBRATION_V2_SOURCE_FREEZE.json", "CALIBRATION_V2_SOURCE_PUBLICATION.json")
    spec = json.loads((ROOT / "protocol_v2.json").read_text())
    if args.worker:
        worker(args.worker, spec)
        return
    if args.child:
        raise SystemExit(run(spec))
    raise SystemExit(outer(__spec__.name, ROOT / "CALIBRATION_V2_PROCESS_RECEIPT.json", ROOT / "calibration_v2_01/WORKER_RECEIPTS.json"))


if __name__ == "__main__":
    main()
