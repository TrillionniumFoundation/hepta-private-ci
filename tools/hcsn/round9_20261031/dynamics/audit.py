"""Frozen before/after audit for continuous integral repairs; no mesh proof."""

import argparse
import hashlib
import importlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import scipy

from .references import deterministic_count, log_time_count, second_maximum_reference


def load_source(source_root):
    path = source_root / "tools/hcsn/round8_20261031/event_dynamics"
    identity = str(path.resolve()).encode() + (path / "event_kernel.py").read_bytes() + (path / "renewal.py").read_bytes()
    name = "repair_checked_" + hashlib.sha256(identity).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, path / "__init__.py",
                                                 submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return (importlib.import_module(name + ".event_kernel"),
            importlib.import_module(name + ".renewal"), path)


def audit(source_root):
    started = time.perf_counter()
    protocol_path = Path(__file__).with_name("protocol.json")
    protocol = json.loads(protocol_path.read_text())
    kernel, renewal, source_path = load_source(source_root)
    gates, moving_rows, renewal_rows = [], [], []

    def gate(name, passed, criterion):
        gates.append(dict(name=name, passed=bool(passed), criterion=criterion))

    moving = protocol["second_segment"]
    for duration in moving["second_duration"]:
        for crossing in moving["crossing_z"]:
            def calculate(z):
                return kernel.two_segment_first_hit(1., (1., 0., .5),
                                                     (duration, (1. + .5 * z) / duration, .5))

            actual = calculate(crossing)
            reference = second_maximum_reference(crossing, duration)
            derivatives = []
            for step in moving["derivative_steps"]:
                numeric = (calculate(crossing + step)["probability"]
                           - calculate(crossing - step)["probability"]) / (2 * step)
                independent = (second_maximum_reference(crossing + step, duration)["probability"]
                               - second_maximum_reference(crossing - step, duration)["probability"]) / (2 * step)
                derivatives.append(dict(step=step, actual=numeric, reference=independent,
                                        absolute_error=abs(numeric - independent)))
            moving_rows.append(dict(duration=duration, crossing_z=crossing, actual=actual,
                                    reference=reference, derivatives=derivatives,
                                    absolute_probability_error=abs(actual["probability"] - reference["probability"])))
    gate("second_leg_transition_probability", max(r["absolute_probability_error"] for r in moving_rows)
         < moving["maximum_probability_error"], "Fixed transition-layer error < 3e-11 against independent maximum-density integral")
    gate("second_leg_transition_gradient", max(d["absolute_error"] for r in moving_rows for d in r["derivatives"])
         < moving["maximum_z_derivative_error"], "All three finite-difference resolutions agree with independent reference within 3e-6")

    config = protocol["renewal"]
    names = ((0, "initial_gap"), (1, "reset_gap"), (2, "drift"), (3, "sigma"), (5, "recovery_mean"))
    limit = deterministic_count(config["initial_gap"], config["reset_gap"], config["drift"],
                                config["time"], config["recovery_mean"], config["phases"])
    for sigma in config["sigma"]:
        parameters = [config["initial_gap"], config["reset_gap"], config["drift"], sigma,
                      config["time"], config["recovery_mean"]]
        reference = log_time_count(*parameters, phases=config["phases"], terms=config["reference_event_terms"])
        row = dict(parameters=parameters, reference=reference)
        try:
            actual = renewal.expected_count(*parameters, phases=config["phases"], tail_tolerance=config["tail_tolerance"])
            extended = renewal.expected_count(*parameters, phases=config["phases"],
                                              included_events=actual["included_events"] + config["event_count_extension"])
            gradients = []
            for index, name in names:
                step = min(.05 * sigma, 1e-5) if name == "sigma" else config["gradient_step_relative"] * parameters[index]
                plus, minus = parameters.copy(), parameters.copy()
                plus[index] += step
                minus[index] -= step
                numeric = (log_time_count(*plus)["expected_count"] - log_time_count(*minus)["expected_count"]) / (2 * step)
                gradients.append(dict(parameter=name, step=step, actual=actual["gradient"][name], reference=numeric,
                                      absolute_error=abs(actual["gradient"][name] - numeric)))
            row.update(actual=actual, gradients=gradients,
                       absolute_count_error=abs(actual["expected_count"] - reference["expected_count"]),
                       extended_gradient_difference=max(abs(extended["gradient"][name] - actual["gradient"][name]) for _, name in names),
                       deterministic_count_difference=actual["expected_count"] - limit["expected_count"])
        except (ValueError, ArithmeticError) as error:
            row["failure"] = dict(type=type(error).__name__, message=str(error))
        renewal_rows.append(row)
    complete = all("actual" in row for row in renewal_rows)
    gate("low_noise_renewal_resolves", complete, "All registered positive-drift noise scales are evaluated without internal quadrature domain failure")
    gate("low_noise_renewal_count", complete and max(r.get("absolute_count_error", math.inf) for r in renewal_rows)
         < config["maximum_count_error"], "Count error < 3e-10 against independent log-time density integrals")
    gate("low_noise_renewal_gradient", complete and all(max(g["absolute_error"] for g in r["gradients"])
         < config["maximum_gradient_error"] for r in renewal_rows), "Five analytic parameter gradients agree with independent finite differences within 3e-7")
    gate("renewal_gradient_event_extension", complete and max(r.get("extended_gradient_difference", math.inf) for r in renewal_rows)
         < config["maximum_extended_gradient_difference"], "Four extra renewal terms change registered gradients < 3e-8; this is not a derivative-tail theorem")
    samples = renewal.sample_counts(config["initial_gap"], config["reset_gap"], config["drift"], config["sigma"][-1],
                                   config["time"], config["recovery_mean"], paths=config["monte_carlo_paths"], seed=config["monte_carlo_seed"])
    standard_error = float(samples.std(ddof=1) / math.sqrt(len(samples)))
    monte_carlo = dict(mean=float(samples.mean()), standard_error=standard_error, paths=len(samples),
                       seed=config["monte_carlo_seed"], histogram=np.bincount(samples).tolist())
    gate("independent_event_time_sampling", complete and abs(monte_carlo["mean"] - renewal_rows[-1].get("actual", {}).get("expected_count", math.inf))
         < config["monte_carlo_standard_error_multiplier"] * standard_error, "Exact Wald/Gamma Monte Carlo agrees within 5 sampling standard errors")
    return dict(schema="hcsn_round9_continuous_repair_v1", gates=gates, all_gates_pass=all(g["passed"] for g in gates),
                protocol_sha256=hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
                audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_path.glob("*.py"))},
                reference_sha256=hashlib.sha256(Path(__file__).with_name("references.py").read_bytes()).hexdigest(),
                environment=dict(numpy=np.__version__, scipy=scipy.__version__), wall_seconds=time.perf_counter()-started,
                moving=moving_rows, renewal=renewal_rows, deterministic_limit=limit, monte_carlo=monte_carlo,
                limitations=protocol["preserve"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record-baseline", action="store_true")
    args = parser.parse_args()
    result = audit(args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(dict(gates=result["gates"], wall_seconds=result["wall_seconds"], output=str(args.output)), indent=2))
    if not result["all_gates_pass"] and not args.record_baseline:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
