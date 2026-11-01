"""Write-once discriminating checks; retain every ordinary and negative row."""

import argparse
import datetime
import hashlib
import json
import platform
import sys
import time
import traceback
from pathlib import Path


def run(out):
    root = Path(__file__).resolve().parents[3]
    here = Path(__file__).resolve().parent
    protocol = json.loads((here / "PROTOCOL.json").read_text())
    sources = list(here.glob("*.py")) + [here / "PROTOCOL.json",
        root / "experiments/hcsn_regeneration_content_20261031/renewal.py",
        root / "experiments/hcsn_validation_r12_20261031/numerics/dynamics.py"]
    snapshot = out / "source_snapshot"
    snapshot.mkdir()
    identities = []
    for source in sorted(sources):
        raw = source.read_bytes(); relative = str(source.relative_to(root))
        saved = snapshot / relative
        saved.parent.mkdir(parents=True, exist_ok=True); saved.write_bytes(raw)
        identities.append({"path": relative, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob_sha1": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()})
    def write(name, value):
        with (out / name).open("x") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
    write("SOURCE_FREEZE.json", {"utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "kind": "local source and thresholds frozen before numerical execution",
        "upstream_delivery_commit": protocol["upstream_delivery_commit"], "files": identities})
    import numpy as np
    import scipy
    import mpmath as mp
    from experiments.hcsn_validation_r14_20261101.numerics.zero_delay import ZeroDelayFlow
    from experiments.hcsn_validation_r14_20261101.numerics.continuous_reference import successor, count_gradient
    write("RUNTIME.json", {"python": sys.version, "executable": sys.executable,
        "platform": platform.platform(), "numpy": np.__version__, "scipy": scipy.__version__,
        "mpmath": mp.__version__, "energy_joules": None})
    gates = protocol["gates"]
    edges = np.array([np.inf if x == "infinity" else x for x in protocol["active_bin_edges"]])
    rows, raw_states, cache = [], {}, {}
    stream = (out / "cases.jsonl").open("x")
    def record(name, passed, expected_failure=False, **details):
        row = {"name": name, "passed": bool(passed), "expected_failure": expected_failure, **details}
        rows.append(row); stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n"); stream.flush()
    def flow(case, h, cap=None):
        return ZeroDelayFlow(**{k: case[k] for k in ("x", "mu", "sigma", "reset")},
            spacing=h, upper=protocol["upper"], count_cap=protocol["count_cap"] if cap is None else cap)
    def absolute_max(x):
        return float(np.max(np.abs(x)))
    def l1(x, y):
        return float(np.abs(np.asarray(x) - np.asarray(y)).sum())
    started = time.perf_counter()
    for case in protocol["cases"]:
        name = case["name"]
        ref = successor(case, edges, protocol["count_cap"])
        write(f"{name}_continuous_reference.json", ref)
        reference_error = max(abs(ref["active_mass"] - 1), abs(sum(ref["active_bins"]) - 1),
                              abs(sum(ref["count_pmf_with_overflow"]) - 1))
        record("continuous_reference_mass_and_tail", reference_error <= gates["reference_mass_atol"]
            and ref["omitted_probability_bound"] <= gates["reference_omitted_probability_max"],
            case=name, mass_error=reference_error, reference=ref)
        errors = []
        for grid_index, h in enumerate(protocol["spacings"]):
            direct = flow(case, h)
            initial = direct.observables(edges)
            immediate = int(case["x"] == 0)
            record("initial_boundary_atom_and_zero_time", initial["expected_count"] == immediate
                and initial["first_hit"] == immediate and initial["mass"] == 1,
                case=name, spacing=h, observed=initial)
            direct.advance_to(case["horizon"])
            observed = direct.observables(edges)
            error = {"expected_count": abs(observed["expected_count"] - ref["expected_count"]),
                "first_hit": abs(observed["first_hit"] - ref["first_hit"]),
                "count_pmf_l1": l1(observed["count_pmf_with_overflow"], ref["count_pmf_with_overflow"]),
                "active_bins_l1": l1(observed["active_bins"], ref["active_bins"])}
            errors.append(sum(error.values()))
            record("finite_state_integrity", abs(observed["mass"] - 1) <= gates["mass_atol"]
                and observed["minimum_probability"] >= gates["minimum_probability"]
                and observed["upper_loss"] <= gates["upper_loss_max"], case=name, spacing=h,
                observed=observed, continuous_error=error, joint_error=errors[-1])
            segmented = flow(case, h)
            partitions = [case["horizon"] * v for v in protocol["partition_fractions"]] + [case["horizon"]]
            for t in partitions:
                segmented.advance_to(t)
            delta = l1(direct.state, segmented.state)
            record("arbitrary_time_complete_state_partition", delta <= gates["partition_full_state_l1"],
                case=name, spacing=h, physical_times=partitions, full_state_l1=delta,
                final_count_difference=abs(float(direct.state[-1] - segmented.state[-1])))
            key = f"{name}_grid_{grid_index}"
            raw_states[key + "_direct"] = direct.state
            raw_states[key + "_segmented"] = segmented.state
            cache[(name, h)] = direct
            if grid_index == len(protocol["spacings"]) - 1:
                limits = [gates[k] for k in ("finest_count_atol", "finest_first_hit_atol",
                                           "finest_count_pmf_l1", "finest_active_bins_l1")]
                record("finest_continuous_successor", all(a <= b for a, b in zip(error.values(), limits)),
                       case=name, spacing=h, errors=error, limits=limits)
        for i in (1, 2):
            record("independent_continuum_grid_refinement", errors[i] <= gates["joint_refinement_factor"] * errors[i - 1],
                case=name, coarse_spacing=protocol["spacings"][i - 1], fine_spacing=protocol["spacings"][i],
                coarse_joint_error=errors[i - 1], fine_joint_error=errors[i],
                maximum_ratio=gates["joint_refinement_factor"])
    negative_case = protocol["cases"][0]
    h = protocol["spacings"][1]
    direct = cache[(negative_case["name"], h)]
    collapsed = flow(negative_case, h).advance_to(protocol["negative_mean_split"])
    before = collapsed.state.copy(); collapsed.collapse_active_layers()
    after = collapsed.state.copy(); collapsed.advance_to(negative_case["horizon"])
    raw_states["negative_mean_before"] = before; raw_states["negative_mean_after"] = after
    raw_states["negative_mean_final"] = collapsed.state
    difference = l1(direct.state, collapsed.state)
    record("collapsed_distribution_equivalence", difference <= gates["partition_full_state_l1"], True,
        full_state_l1=difference, count_difference=abs(float(direct.state[-1] - collapsed.state[-1])))
    record("collapsed_distribution_detected", difference >= gates["negative_detection_min"],
        full_state_l1=difference, initial_mass_difference=abs(float(before[:-1].sum() - after[:-1].sum())))
    one_event_count = direct.observables(edges)["first_hit"]
    count_error = abs(float(direct.state[-1]) - one_event_count)
    record("at_most_one_event_equivalence", count_error <= gates["finest_count_atol"], True,
        actual_count=float(direct.state[-1]), endpoint_reset_count=one_event_count, count_error=count_error)
    record("at_most_one_event_detected", count_error >= gates["negative_detection_min"], count_error=count_error)
    self_case = dict(protocol["self_reset"])
    horizon = self_case.pop("horizon"); event_rate = self_case.pop("event_rate")
    same = ZeroDelayFlow(**self_case, count_cap=protocol["count_cap"]).advance_to(horizon)
    mean = horizon * event_rate
    import math
    pmf = [math.exp(-mean) * mean**n / math.factorial(n) for n in range(protocol["count_cap"] + 1)]
    pmf.append(1 - sum(pmf)); same_obs = same.observables(edges)
    self_error = max(l1(same_obs["count_pmf_with_overflow"], pmf), abs(same_obs["expected_count"] - mean))
    record("self_reset_events_survive_unchanged_physical_state", self_error <= gates["self_reset_atol"],
        observed=same_obs, poisson_pmf=pmf, expected_count=mean, maximum_error=self_error)
    raw_states["self_reset_poisson"] = same.state
    gradient_case = protocol["gradient_case"]
    references = [count_gradient(gradient_case, n, protocol["gradient_precision_digits"])
                  for n in protocol["gradient_reference_terms"]]
    write("CONTINUOUS_GRADIENT_REFERENCE.json", references)
    with mp.workdps(protocol["gradient_precision_digits"]):
        reference_difference = float(max(abs(mp.mpf(a) - mp.mpf(b))
            for a, b in zip(references[0]["gradient"], references[1]["gradient"])))
    record("high_precision_gradient_tail_refinement", reference_difference <= gates["gradient_reference_sum_difference"],
           maximum_difference=reference_difference)
    gradient_reference = np.array([float(x) for x in references[-1]["gradient"]])
    gradient_errors, tangents = [], {}
    for h in protocol["spacings"]:
        model = flow(gradient_case, h, cap=0)
        tangent = model.count_sensitivities(gradient_case["horizon"])
        model.advance_to(gradient_case["horizon"])
        value_error = abs(tangent["expected_count"] - float(model.state[-1]))
        error = absolute_max(np.array(tangent["gradient"]) - gradient_reference)
        gradient_errors.append(error); tangents[h] = tangent
        record("count_tangent_uses_same_generator", value_error <= gates["partition_full_state_l1"],
            spacing=h, tangent=tangent, marked_count=float(model.state[-1]),
            same_generator_value_error=value_error, continuous_gradient=gradient_reference.tolist(),
            continuous_gradient_max_abs_error=error)
    record("finest_continuous_gradient", gradient_errors[-1] <= gates["gradient_finest_max_abs"],
        error=gradient_errors[-1], limit=gates["gradient_finest_max_abs"])
    record("continuous_gradient_grid_refinement", gradient_errors[-1] <= gates["gradient_fine_to_coarse_factor"] * gradient_errors[0],
        coarse_error=gradient_errors[0], middle_error=gradient_errors[1], fine_error=gradient_errors[-1],
        maximum_fine_to_coarse_ratio=gates["gradient_fine_to_coarse_factor"])
    h = protocol["gradient_fd_spacing"]
    for step in protocol["finite_difference_steps"]:
        finite_difference = []
        for parameter in protocol["gradient_order"]:
            plus, minus = dict(gradient_case), dict(gradient_case)
            plus[parameter] += step; minus[parameter] -= step
            upper = flow(plus, h, cap=0).advance_to(plus["horizon"]).state[-1]
            lower = flow(minus, h, cap=0).advance_to(minus["horizon"]).state[-1]
            finite_difference.append(float((upper - lower) / (2 * step)))
        difference = absolute_max(np.array(finite_difference) - tangents[h]["gradient"])
        record("finite_generator_tangent_independent_difference", difference <= gates["gradient_fd_max_abs"],
            step=step, spacing=h, finite_difference=finite_difference, tangent=tangents[h]["gradient"], maximum_difference=difference)
    rejection_cases = {
        "zero_reset": lambda: ZeroDelayFlow(.4, -.6, .7, 0, .02),
        "zero_noise": lambda: ZeroDelayFlow(.4, -.6, 0, .8, .02),
        "unresolved_positive_atom": lambda: ZeroDelayFlow(.001, -.6, .7, .8, .02),
        "time_reversal": lambda: flow(negative_case, .02).advance_to(-.01),
        "nonfinite_time": lambda: flow(negative_case, .02).advance_to(float("inf")),
        "spatial_knot_derivative": lambda: flow(negative_case, .02).count_sensitivities(1.2)}
    for name, operation in rejection_cases.items():
        try:
            operation()
        except ValueError as error:
            record("reject_undefined_or_unresolved_request", True, case=name, message=str(error))
        else:
            record("reject_undefined_or_unresolved_request", False, case=name)
    np.savez_compressed(out / "RAW_STATES.npz", **raw_states)
    unchanged = all(hashlib.sha256((root / x["path"]).read_bytes()).hexdigest() == x["sha256"] for x in identities)
    record("source_unchanged_during_execution", unchanged)
    stream.close()
    failures = [r for r in rows if not r["passed"]]
    write("FAILURES.json", failures)
    write("SUMMARY.json", {"ordinary_checks": sum(not r["expected_failure"] for r in rows),
        "ordinary_failures": sum(not r["passed"] and not r["expected_failure"] for r in rows),
        "expected_negative_equivalence_failures": sum(r["expected_failure"] and not r["passed"] for r in rows),
        "unexpected_negative_passes": sum(r["expected_failure"] and r["passed"] for r in rows),
        "success": all(r["passed"] != r["expected_failure"] for r in rows),
        "checks": len(rows), "body_wall_seconds": time.perf_counter() - started,
        "not_established": protocol["not_established"], "energy_joules": None,
        "raw_states_sha256": hashlib.sha256((out / "RAW_STATES.npz").read_bytes()).hexdigest()})
    return all(r["passed"] != r["expected_failure"] for r in rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        success = run(args.out.resolve())
    except Exception as error:
        with (args.out / "EXCEPTION.json").open("x") as stream:
            json.dump({"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}, stream, indent=2)
        raise
    raise SystemExit(0 if success else 1)
