"""Registered moving-boundary Brownian versus grid/Erlang convergence audit."""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import quad

from brownian_reference import Case, sample, statistics
from finite_volume_reference import lower_domain_bound, solve

CASES = (
    Case("linear_rise", (0., 2.), (.75, 1.10), .60, .65, -.20, .27, .05),
    Case("linear_fall", (0., 2.), (1.15, .70), .30, .75, -.25, .31, .10),
    Case("turning_boundary", (0., .25, .55, 1.10, 1.70), (.85, .55, .95, .60, .80),
         .65, .50, -.15, .23, .25),
)
LEVELS = ((24, 6, 32), (48, 12, 64), (96, 24, 128), (192, 48, 256))
TOLERANCE = dict(events=.025, ever=.02, refractory=.02, mean=.035, variance=.05)


def write(path, content):
    path.write_text(json.dumps(content, indent=2, allow_nan=False)+"\n")


def calibration():
    case = Case("sampler_calibration", (0., 1.), (.9, .9), .3, .7, -.1, 2., .05)
    raw = sample(case, 12_000, 2026103101)
    gap, vol, drift, horizon = .85, .7, -.3, 1.
    def density(t):
        return gap*math.exp(-(gap+drift*t)**2/(2*vol*vol*t))/(vol*math.sqrt(2*math.pi*t**3)) if t else 0.
    probability = quad(density, 0., horizon, epsabs=2e-12)[0]
    scale, mean = vol*math.sqrt(horizon), gap+drift*horizon
    def killed(y):
        return math.exp(-.5*((y-mean)/scale)**2)/(scale*math.sqrt(2*math.pi)) * (-math.expm1(-2*gap*y/(vol*vol*horizon)))
    expected_mean = quad(lambda y: (.9-y)*killed(y), 0., math.inf, epsabs=2e-12)[0]/(1-probability)
    empirical = statistics(raw)["ever"]
    surviving = raw["position"][raw["counts"] == 0]
    surviving_se = float(surviving.std(ddof=1)/math.sqrt(len(surviving)))
    z_hit = abs(empirical["value"]-probability)/empirical["standard_error"]
    z_survivor = abs(float(surviving.mean())-expected_mean)/surviving_se
    assert z_hit < 6 and z_survivor < 6 and int(raw["counts"].max()) <= 1
    return dict(scope="Calibration of the new sampler only, not new static production evidence",
                samples=12_000, independent_probability=probability, empirical=empirical,
                independent_survivor_mean=expected_mean, empirical_survivor_mean=float(surviving.mean()),
                hit_z=z_hit, survivor_mean_z=z_survivor, passed=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=40_000)
    args = parser.parse_args()
    if args.samples < 1000:
        raise ValueError("At least 1000 independent paths required")
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    files = ("brownian_reference.py", "finite_volume_reference.py", "moving_audit.py")
    hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}
    registration = dict(schema="hcsn.round10.moving.registration.v1", cases=[asdict(c) for c in CASES],
        levels=LEVELS, samples_per_case=args.samples, seed_base=2026103120,
        absolute_fine_grid_tolerances=TOLERANCE, mc_standard_errors_allowed=6,
        lower=-5., source_sha256=hashes,
        law="True Brownian continuous boundary; fixed delay; frozen absolute reset during delay",
        numeric_law="Finite reflecting upwind CTMC, Erlang refractory, observation-time boundary jumps",
        admission="Research evidence only; not native PyTorch/owner execution or general certification")
    write(args.output/"registration.json", registration)
    started = time.perf_counter()
    calibration_result = calibration()
    write(args.output/"sampler_calibration.json", calibration_result)
    rows = []
    for index, case in enumerate(CASES):
        raw = sample(case, args.samples, 2026103120+index)
        stats = statistics(raw)
        np.savez_compressed(args.output/(case.name+"_samples.npz"), counts=raw["counts"],
                            first_event_time=raw["first"], final_position=raw["position"],
                            refractory=raw["refractory"])
        write(args.output/(case.name+"_mc.json"), dict(case=asdict(case), metrics=stats,
            count_histogram=np.bincount(raw["counts"]).tolist(), traces=raw["traces"],
            survivor_proposals=raw["survivor_proposals"], seed=raw["seed"],
            bit_generator=raw["bit_generator"], samples=args.samples))
        print(json.dumps(dict(case=case.name, stage="brownian_mc", metrics=stats,
                              elapsed=time.perf_counter()-started)), flush=True)
        resolutions = []
        for cells, phases, steps in LEVELS:
            row = solve(case, cells, phases, steps)
            errors = {key: abs(row["metrics"][key]-stats[key]["value"]) for key in TOLERANCE}
            row["absolute_mc_differences"] = errors
            row["scaled_difference_score"] = math.sqrt(sum((errors[k]/TOLERANCE[k])**2 for k in TOLERANCE))
            write(args.output/(case.name+f"_grid_{cells}_{phases}_{steps}.json"), row)
            resolutions.append(dict(cells=cells, stages=phases, steps=steps, metrics=row["metrics"],
                absolute_mc_differences=errors, scaled_difference_score=row["scaled_difference_score"],
                max_mass_error=row["max_mass_error"], max_killed_subset_error=row["max_killed_subset_error"]))
            print(json.dumps(dict(case=case.name, stage="grid", cells=cells, phases=phases,
                absolute_mc_differences=errors, elapsed=time.perf_counter()-started)), flush=True)
        last = resolutions[-1]
        checks = {key: last["absolute_mc_differences"][key] <= TOLERANCE[key]+6*stats[key]["standard_error"]
                  for key in TOLERANCE}
        rows.append(dict(case=case.name, monte_carlo=stats, resolutions=resolutions,
            finest_metric_acceptance=checks, finest_accepted=all(checks.values()),
            coupled_refinement_reduced_scaled_difference=last["scaled_difference_score"] < resolutions[0]["scaled_difference_score"],
            fixed_delay_lower_domain_coupling_bound=lower_domain_bound(case, -5.),
            repeat_events_minus_first_event_probability=stats["events"]["value"]-stats["ever"]["value"]))
    changed = [name for name in files if hashlib.sha256((root/name).read_bytes()).hexdigest() != hashes[name]]
    summary = dict(schema="hcsn.round10.moving.result.v1", cases=rows, calibration=calibration_result,
        passed=all(r["finest_accepted"] and r["coupled_refinement_reduced_scaled_difference"] for r in rows) and not changed,
        source_sha256=hashes, changed_sources=changed, wall_seconds=time.perf_counter()-started,
        environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
        scope="Joint refinement evidence for these three schedules, not separated error certification or native implementation validation")
    write(args.output/"summary.json", summary)
    print(json.dumps(dict(passed=summary["passed"], output=str(args.output), wall_seconds=summary["wall_seconds"])), flush=True)
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
