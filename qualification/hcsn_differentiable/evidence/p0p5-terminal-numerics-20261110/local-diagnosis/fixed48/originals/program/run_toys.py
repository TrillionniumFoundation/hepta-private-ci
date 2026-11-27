"""The fixed48 scalar diagnostic roster; standard library only, one invocation."""

import time

PROCESS_STARTED = time.monotonic()

import argparse
import ast
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import traceback


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    payload = path.read_bytes()
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def verify(program, manifest_sha):
    path = program / "PROGRAM-MANIFEST.json"
    require(identity(path)["sha256"] == manifest_sha, "program manifest changed")
    entries = json.loads(path.read_text())["files"]
    for name, expected in entries.items():
        source = program / name
        require(source.resolve().is_relative_to(program) and not source.is_symlink(), "unsafe source path")
        require(identity(source) == expected, "program input changed: " + name)
    return entries


def gauss_rule_builder(program):
    source = program / "source-inputs/operator.py"
    require(identity(source)["sha256"] == "cb3eed1bcfbd3b10cc331a193a5d4b6a3d4309db899e0d8f821477f97b7dbdc1", "unrecognized Gauss source")
    tree = ast.parse(source.read_bytes())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_gauss_legendre_unit")
    namespace = {"math": math, "lru_cache": lru_cache}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["_gauss_legendre_unit"]


def sf(z):
    return .5 * math.erfc(z / math.sqrt(2))


def phi(z):
    return math.exp(-.5 * z * z) / math.sqrt(2 * math.pi)


def logsumexp(values):
    maximum = max(values)
    return maximum + math.log(math.fsum(math.exp(v - maximum) for v in values))


def active_case(case, rules):
    width, sigma, order = case["width"], .35, case["order"]
    nodes, weights = rules[order]
    nearest = width * min(nodes)
    h_star = (nearest / sigma) ** 2
    h = case["h"] if case["h"] is not None else case["h_star_factor"] * h_star
    scale, A = sigma * math.sqrt(h), width / (sigma * math.sqrt(h))
    density_A, density_2A = phi(A), phi(2 * A)
    B_A = density_A - A * sf(A)
    B_2A = density_2A - 2 * A * sf(2 * A)
    bracket = math.fsum((phi(0), -2 * B_A, B_2A))
    reference = (scale / width) * bracket
    require(0 < reference < 1, "free-cell reference is unresolved")
    terms, log_bounds, zero_upper_terms = [], [], 0
    for node, weight in zip(nodes, weights):
        # Uniform source x=width*node and right target[width,2*width].
        z = (width - width * node) / scale
        upper_z = z + A
        left, right = sf(z), sf(upper_z)
        term = weight * (left - right)
        require(term >= 0 and math.isfinite(term), "negative/nonfinite Gauss contribution")
        terms.append(term)
        if left == 0:
            zero_upper_terms += 1
        # For z>0, SF(z)<phi(z)/z is a mathematical Mills bound.
        # Its log is evaluated in FP64; no certified libm error bound is claimed.
        require(z > 0, "node touched target boundary")
        log_bounds.append(math.log(weight) - .5 * z * z - .5 * math.log(2 * math.pi) - math.log(z))
    projected = math.fsum(terms)
    require(0 <= projected <= 1 and math.isfinite(projected), "Gauss probability unresolved")
    difference = projected - reference
    # Explicit engineering scale only; not an upper error bound for erfc/exp.
    scale_estimate = 64 * (math.ulp(reference) + math.ulp(projected)
                           + (scale / width) * (math.ulp(phi(0)) + 2 * math.ulp(B_A) + math.ulp(B_2A)))
    return {
        **case, "h": h, "h_star": h_star, "h_over_h_star": h / h_star,
        "minimum_unit_node": min(nodes), "nearest_node_distance": nearest,
        "nearest_node_over_diffusion_length": nearest / scale,
        "exact_uniform_free_cell_probability_FP64": reference,
        "fixed_Gauss_free_cell_probability_FP64": projected,
        "signed_difference_FP64": difference,
        "signed_relative_difference_FP64": difference / reference,
        "absolute_relative_difference_FP64": abs(difference) / reference,
        "exact_p_over_sqrt_h": reference / math.sqrt(h),
        "Gauss_p_over_sqrt_h": projected / math.sqrt(h),
        "exact_p_over_h": reference / h, "Gauss_p_over_h": projected / h,
        "exact_small_h_coefficient": sigma / (width * math.sqrt(2 * math.pi)),
        "Gauss_positive_mass_underflowed": projected == 0,
        "source_node_SF_values_underflowed": zero_upper_terms,
        "log_Mills_upper_bound_for_Gauss_probability_FP64": min(0.0, logsumexp(log_bounds)),
        "roundoff_scale_estimate": scale_estimate,
        "scale_is_a_certified_error_bound": False,
        "difference_exceeds_roundoff_scale_estimate": abs(difference) > scale_estimate,
        "resolution_status": "Gauss_positive_mass_underflowed" if projected == 0 else ("difference_above_roundoff_scale" if abs(difference) > scale_estimate else "difference_sign_inconclusive_at_roundoff_scale"),
        "physical_scope": "free Gaussian kernel, mu0, same uniform source/adjacent target; no killed boundary, tail, refractory or resolvent",
    }


def phase_case(case):
    j, width, elapsed = 16, .2 / 16, .1
    ratio, h = case["h_over_width"], case["h_over_width"] * width
    n = round(elapsed / h)
    require(abs(n * h - elapsed) < 1e-14 and n >= j, "nonintegral fixed phase observation")
    release = math.fsum(math.comb(n, k) * ratio**k * (1 - ratio) ** (n - k) for k in range(j, n + 1))
    physical_uniform_release = min(1., max(0., (elapsed - (j - 1) * width) / width))
    return {**case, "phase_width": width, "j_one_based": j, "h": h, "steps": n, "observation_time": elapsed,
            "projected_isolated_release_probability": release, "same_initial_uniform_physical_release_probability": physical_uniform_release,
            "geometric_chain_mean_wait": j * width, "geometric_chain_wait_variance": j * width**2 * (1 - ratio),
            "h_to_zero_Erlang_mean": j * width, "h_to_zero_Erlang_variance": j * width**2,
            "initial_physical_uniform_mean": (j - .5) * width, "initial_physical_uniform_variance": width**2 / 12,
            "scope": "isolated phase labels with absorbing release; not reset/active coupled HCSN"}


def tail_case(case):
    sigma, mu, rho, endpoint, rate = .35, -.12, .15, 4.8, 1.
    kappa = (mu + math.sqrt(mu * mu + 2 * rho * sigma * sigma)) / (sigma * sigma)
    reconstructed = math.exp(-kappa * endpoint) * rate / (rate + kappa)
    moment = math.exp(-kappa * (endpoint + case["shift"])) * rate / (rate + kappa)
    return {**case, "Q_tail_coefficient": 1., "endpoint": endpoint, "tail_rate": rate,
            "mu": mu, "sigma": sigma, "discount": rho, "kappa": kappa,
            "actual_law_mean": endpoint + case["shift"] + 1 / rate, "R_reconstructed_mean": endpoint + 1 / rate,
            "analytic_shifted_tail_first_hit_Laplace_moment_FP64": moment,
            "R_same_coefficient_first_hit_Laplace_moment_FP64": reconstructed,
            "shifted_over_reconstructed_ratio": moment / reconstructed,
            "predicted_translation_ratio": math.exp(-kappa * case["shift"]),
            "scope": "hypothetical two positive tail laws with identical projected coefficient; no real posterior tail read"}


def main(args):
    program, out = args.program.resolve(), args.output.resolve()
    require(0 < args.wall_seconds <= 120, "invalid scalar wall grant")
    require(out.is_dir() and not (out / "RESULT.json").exists(), "output not exclusively admitted")
    manifest = verify(program, args.manifest_sha256)
    decision = json.loads((program / "ROOT-DECISION-TRANSCRIPTION.json").read_text())
    require(decision["execution_authorized"] is True and decision["maximum_runs"] == 1, "missing single-run authority")
    plan = json.loads((program / "FOLLOWUP-PLAN.json").read_text())
    require(plan["execution_authorized"] is False, "original design snapshot was changed")
    roster = json.loads((program / "ROSTER.json").read_text())["cases"]
    require(len(roster) == 48 and len({r["id"] for r in roster}) == 48, "fixed48 roster mismatch")
    builder = gauss_rule_builder(program)
    rules = {order: builder(order) for order in (16, 32, 64)}
    for order, (nodes, weights) in rules.items():
        require(len(nodes) == len(weights) == order and all(0 < x < 1 for x in nodes), "Gauss nodes")
        require(all(w > 0 for w in weights) and abs(math.fsum(weights) - 1) < 1e-14, "Gauss weights")
    save(out / "GAUSS-RULES.json", {str(order): {"nodes": nodes, "weights": weights} for order, (nodes, weights) in rules.items()})
    results = []
    with (out / "cases.jsonl").open("x") as journal:
        for case in roster:
            tick, cpu = time.monotonic(), time.process_time()
            if tick - PROCESS_STARTED >= args.wall_seconds:
                row = {**case, "execution_status": "unrun_budget_exhausted", "known_case_CPU_seconds": 0., "known_case_wall_seconds": 0.}
            else:
                try:
                    result = {"active": active_case, "phase": phase_case, "tail": tail_case}[case["kind"]]
                    row = result(case, rules) if case["kind"] == "active" else result(case)
                    row["execution_status"] = "computed_scalar_case"
                except Exception:
                    row = {**case, "execution_status": "failed_preserved_no_retry", "error": traceback.format_exc()}
                row.update(known_case_wall_seconds=time.monotonic() - tick, known_case_CPU_seconds=time.process_time() - cpu)
            results.append(row)
            journal.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
    error, source_unchanged = None, False
    try:
        require(verify(program, args.manifest_sha256) == manifest, "final source identity mismatch")
        source_unchanged = True
        require(time.monotonic() - PROCESS_STARTED <= args.wall_seconds, "worker exceeded wall grant")
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 <= 268435456, "worker RSS exceeded cap")
    except Exception:
        error = traceback.format_exc()
    result = {"schema": "hcsn-fixed48-scalar-diagnosis-v1", "status": "completed_fixed48_scalar_roster" if error is None and all(r["execution_status"] == "computed_scalar_case" for r in results) else "failed_or_incomplete_preserved",
              "cases": results, "program_manifest_sha256": args.manifest_sha256, "source_unchanged": source_unchanged,
              "final_guard_error": error, "planned_cases": 48, "computed_cases": sum(r["execution_status"] == "computed_scalar_case" for r in results),
              "unrun_cases": sum(r["execution_status"] == "unrun_budget_exhausted" for r in results), "case_failures": sum(r["execution_status"] == "failed_preserved_no_retry" for r in results),
              "scientific_admission": "HOLD", "training_domain_qualification": "HOLD", "quantitative_attribution_of_existing_pressure_value_failures": False,
              "model_probability_or_E_access": False, "model_oracle_training_calls": 0, "automatic_retries": 0,
              "runtime": {"python": sys.version, "executable": sys.executable, "platform": sys.platform},
              "CPU_prefix_seconds": time.process_time(), "process_wall_prefix_seconds": time.monotonic() - PROCESS_STARTED,
              "self_peak_RSS_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "timing_scope": "Worker prefix before result serialization and exit. Exact complete worker wait4 and wall belong in external EXECUTION.json; per-case timers are nested.",
              "roundoff_scope": "Scalar reference and erfc/exp are FP64. Engineering ULP scales are not certified function-error bounds. Zero Gauss mass may be unresolved positive mass with a logged Mills bound."}
    save(out / "RESULT.json", result)
    print(json.dumps({"status": result["status"], "computed_cases": result["computed_cases"], "source_unchanged": result["source_unchanged"]}), flush=True)
    return 0 if result["status"] == "completed_fixed48_scalar_roster" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--wall-seconds", type=float, required=True)
    raise SystemExit(main(parser.parse_args()))
