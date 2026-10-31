"""Independent density, integer-allocation and actual-native Q24 guard checks."""

import argparse
from decimal import Decimal, localcontext
import hashlib
import itertools
import json
import math
from pathlib import Path
import tempfile
import time

import numpy as np
from scipy.integrate import quad
from scipy.special import logsumexp

from ..analytic import event_log_probs
from ..native_adapter import Native
from .quantized_guard import (Q24, _project_integer_simplex, guard_quantized,
                              guard_quantized_scalar, protected_event_quantize,
                              protected_event_quantize_scalar)


def decimal_density_certificate(m0, v0, m1, v1):
    """Independent 90-digit extremum, evaluated directly at stationary x."""
    with localcontext() as context:
        context.prec = 90
        a, b, m, v = [Decimal.from_float(float(x)) for x in (m0, v0, m1, v1)]
        if v == b and m == a:
            return {"supremum": 0.0, "stationary_check_error": 0.0}
        if v <= b:
            return {"supremum": math.inf, "stationary_check_error": 0.0}
        x = (v * a - b * m) / (v - b)
        direct = ((v / b).ln() + (x - m)**2 / v - (x - a)**2 / b) / 2
        bound = (v / b).ln() / 2 + (m - a)**2 / (2 * (v - b))
        return {"supremum": float(bound), "stationary_check_error": float(abs(direct - bound))}


def decimal_event_excess(log_anchor, counts):
    """Check delivered integer masses using independent high-precision log."""
    maximum = -math.inf
    with localcontext() as context:
        context.prec = 90
        for logp, count in zip(log_anchor, counts):
            if not math.isfinite(float(logp)):
                continue
            if int(count) <= 0:
                return math.inf
            delivered = (Decimal(int(count)) / Decimal(Q24)).ln()
            maximum = max(maximum, float(Decimal.from_float(float(logp)) - delivered))
    return maximum


def validate(work_dir, native_dir):
    began = time.perf_counter_ns()
    work_dir, native_dir = Path(work_dir), Path(native_dir)
    work_dir.mkdir(parents=True, exist_ok=False)
    checks, raw_native = [], []

    def check(name, passed, **evidence):
        checks.append({"name": name, "passed": bool(passed), **evidence})

    def rejects(action):
        try:
            action()
        except (ValueError, TypeError, OverflowError):
            return True
        return False

    rng = np.random.default_rng(53073)
    grid = list(itertools.product([-1e4, -7.9, -0.25 / Q24, 0.0, 0.25 / Q24, 7.9, 1e4],
                                  [1e-4, 0.1, 1.0, 7.8, 8.0, 100.0], [-10.0, 0.0, 10.0]))
    m0 = np.array([row[0] for row in grid] + rng.uniform(-1e4, 1e4, 1000).tolist())
    v0 = np.array([row[1] for row in grid] + np.exp(rng.uniform(math.log(1e-4), math.log(100), 1000)).tolist())
    shifts = np.array([row[2] for row in grid] + rng.normal(0, 3, 1000).tolist())
    proposal = m0 + shifts * np.sqrt(v0)
    mean, variance, certificate = guard_quantized(m0, v0, proposal)
    references = [decimal_density_certificate(*row) for row in zip(m0, v0, mean, variance)]
    reference_bound = np.array([r["supremum"] for r in references])
    discrepancy = float(np.max(np.abs(reference_bound - certificate["pointwise_nll_bound"])))
    check("wide_domain_delivered_gaussian_density_envelope", np.all(reference_bound <= 0.02)
          and np.all(variance >= v0) and discrepancy <= 3e-12,
          cases=len(mean), maximum_independent_supremum=float(reference_bound.max()),
          maximum_certificate_error=discrepancy,
          maximum_stationary_check_error=max(r["stationary_check_error"] for r in references),
          native_domain_count=int(certificate["native_typed_domain_mask"].sum()))
    check("parameter_grid_and_scalar_vector_equivalence", np.array_equal(mean * Q24, certificate["mean_q24"])
          and np.array_equal(variance * Q24, certificate["variance_q24"])
          and guard_quantized_scalar(m0[0], v0[0], proposal[0])["mean"] == mean[0])

    # A narrower rounded variance or a changed mean at equal variance makes the
    # pointwise density loss unbounded, despite a zero pre-rounding guard loss.
    examples = [(0.0, 1 + 0.25 / Q24), (0.25 / Q24, 1.0)]
    counterexamples = []
    for anchor_mean, anchor_variance in examples:
        naive_mean = float(np.rint(anchor_mean * Q24) / Q24)
        naive_variance = float(np.rint(anchor_variance * Q24) / Q24)
        result = decimal_density_certificate(anchor_mean, anchor_variance, naive_mean, naive_variance)
        guarded = guard_quantized_scalar(anchor_mean, anchor_variance, anchor_mean)
        counterexamples.append({"anchor": [anchor_mean, anchor_variance],
                                "naive": [naive_mean, naive_variance],
                                "naive_supremum_unbounded": math.isinf(result["supremum"]),
                                "guarded": guarded})
    check("naive_parameter_quantization_does_not_inherit_fp64_guard",
          all(row["naive_supremum_unbounded"] for row in counterexamples), counterexamples=counterexamples)

    normalizer = np.array([[0.0, -800.0, -1e6], [-1e300, 0.0, -1e300],
                           [-math.inf, 0.0, -math.inf], [-0.01, -6.0, -5.0]])
    normalizer -= logsumexp(normalizer, axis=1, keepdims=True)
    anchor_logp = np.vstack([normalizer, np.log(rng.dirichlet([0.3, 0.8, 1.2], 1000))])
    candidates = np.vstack([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0],
                            rng.dirichlet([0.4, 0.7, 1.1], 1000)])
    counts, event_certificate = protected_event_quantize(anchor_logp, candidates)
    event_reference = np.array([decimal_event_excess(logp, count) for logp, count in zip(anchor_logp, counts)])
    check("categorical_q24_pointwise_logscore_and_underflow_support",
          np.all(event_reference <= 0.02) and np.all(counts.sum(1) == Q24)
          and np.all((counts > 0) | ~np.isfinite(anchor_logp)),
          cases=len(counts), maximum_independent_excess=float(event_reference.max()),
          maximum_certificate_error=float(np.max(np.abs(event_reference - event_certificate["maximum_event_nll_excess"]))),
          extreme_cases=[{"anchor_logp": [None if not np.isfinite(x) else float(x) for x in anchor_logp[i]],
                          "candidate_probs": candidates[i].tolist(), "delivered_counts": counts[i].tolist(),
                          "independent_maximum_excess": float(event_reference[i])} for i in range(4)])
    check("naive_event_zero_has_infinite_rare_event_nll", candidates[0, 1] == 0
          and np.isfinite(anchor_logp[0, 1]) and counts[0, 1] >= 1,
          finite_anchor_log_probability=float(anchor_logp[0, 1]), raw_count=0, protected_count=int(counts[0, 1]))

    # Independent exhaustive integer enumeration at smaller masses validates
    # the same production projection routine, including active lower bounds.
    largest_objective_excess = 0.0
    for _ in range(250):
        mass = int(rng.integers(4, 32))
        floor = rng.multinomial(int(rng.integers(0, mass + 1)), [0.2, 0.3, 0.5])
        target = mass * rng.dirichlet([0.4, 0.6, 1.1])
        actual = _project_integer_simplex(target[None, :], floor[None, :], mass)[0]
        optimum = math.inf
        for first in range(int(floor[0]), mass - int(floor[1] + floor[2]) + 1):
            for second in range(int(floor[1]), mass - first - int(floor[2]) + 1):
                trial = np.array([first, second, mass - first - second])
                optimum = min(optimum, float(np.sum((trial - target)**2)))
        largest_objective_excess = max(largest_objective_excess, float(np.sum((actual - target)**2)) - optimum)
    check("integer_projection_matches_exhaustive_optimum", largest_objective_excess <= 1e-10,
          cases=250, maximum_objective_excess=largest_objective_excess)

    rejection_cases = {
        "negative_epsilon": lambda: guard_quantized(0.0, 1.0, 0.0, -0.1),
        "unsupported_mean": lambda: guard_quantized(10001.0, 1.0, 0.0),
        "unsupported_variance": lambda: guard_quantized(0.0, 1e-5, 0.0),
        "nonfinite_proposal": lambda: guard_quantized(0.0, 1.0, math.inf),
        "categorical_negative_epsilon": lambda: protected_event_quantize(np.log([.2, .3, .5]), [.2, .3, .5], -0.1),
        "categorical_bad_mass": lambda: protected_event_quantize(np.log([.2, .3, .5]), [.2, .3, .4]),
        "categorical_unormalized_anchor": lambda: protected_event_quantize(np.log([.2, .3, .4]), [.2, .3, .5]),
        "infeasible_zero_budget": lambda: protected_event_quantize(np.log([.2, .3, .5]), [.2, .3, .5], 0.0),
    }
    rejections = {name: rejects(action) for name, action in rejection_cases.items()}
    exact_counts, exact_certificate = protected_event_quantize([0.0, -math.inf, -math.inf], [1.0, 0.0, 0.0], 0.0)
    check("guard_domains_and_infeasible_budgets_fail_closed", all(rejections.values())
          and exact_counts.tolist() == [Q24, 0, 0] and float(exact_certificate["maximum_event_nll_excess"]) == 0,
          rejections=rejections, exact_zero_budget_counts=exact_counts.tolist())

    qualified = np.flatnonzero(certificate["native_typed_domain_mask"])
    qualified = qualified[np.linspace(0, len(qualified) - 1, min(36, len(qualified))).astype(int)]
    native_identity_errors = []
    native_density_excess = []
    categorical_excess = []
    maximum_cdf_error = 0.0
    with Native(native_dir / "analytic_event", native_dir / "BUILD_RECEIPT.json") as native:
        for i, index in enumerate(qualified):
            output = native.typed(f"q24.guard.{i}", work_dir / f"case_{i}",
                                  float(mean[index]), float(variance[index]), -0.6, 0.6)
            actual = output["head"]["parameters_q24_decoded"]
            native_identity_errors.append(actual[:2] != [float(mean[index]), float(variance[index])])
            density = decimal_density_certificate(m0[index], v0[index], actual[0], actual[1])
            native_density_excess.append(density["supremum"])
            logs = event_log_probs(m0[index], v0[index], -0.6, 0.6)
            projected = protected_event_quantize_scalar(logs, np.asarray(output["head"]["probabilities_q24"]) / Q24)
            categorical_excess.append(decimal_event_excess(logs, projected["counts"]))
            endpoints = []
            for threshold in actual[2:]:
                z = (threshold - actual[0]) / math.sqrt(actual[1])
                area = quad(lambda x: math.exp(-x*x/2) / math.sqrt(2*math.pi), 0, min(abs(z), 12), epsabs=1e-14)[0]
                endpoints.append(0.5 + math.copysign(area, z))
            reference = np.array([endpoints[0], endpoints[1] - endpoints[0], 1 - endpoints[1]])
            maximum_cdf_error = max(maximum_cdf_error, float(np.max(np.abs(reference - output["head"]["probabilities"]))))
            raw_native.append({"anchor": [float(m0[index]), float(v0[index])],
                               "guarded_parameters": [float(mean[index]), float(variance[index])],
                               "independent_density_certificate": density,
                               "native": output, "delivered_event_projection": projected})
        rounding = []
        for i, number in enumerate([0.5 / Q24, 1.5 / Q24, -0.5 / Q24, -1.5 / Q24]):
            result = native.typed(f"q24.tie.{i}", work_dir / f"tie_{i}", number, 1.0, -0.6, 0.6)
            rounding.append({"input_mean": number, "native_mean": result["head"]["parameters_q24_decoded"][0],
                             "expected_ties_even_mean": float(np.rint(number * Q24) / Q24)})
            raw_native.append({"rounding_fixture": rounding[-1], "native": result})
        native_binary_sha256 = native.receipt["binary_sha256"]
    check("actual_native_ties_even_and_exact_guarded_parameter_roundtrip", not any(native_identity_errors)
          and all(row["native_mean"] == row["expected_ties_even_mean"] for row in rounding),
          guarded_native_cases=len(qualified), rounding_cases=rounding, binary_sha256=native_binary_sha256)
    check("post_native_gaussian_and_separate_categorical_certificates", max(native_density_excess) <= 0.02
          and max(categorical_excess) <= 0.02 and maximum_cdf_error <= 2e-14,
          maximum_gaussian_nll_excess=max(native_density_excess),
          maximum_delivered_categorical_nll_excess=max(categorical_excess),
          maximum_native_cdf_vs_quadrature_error=maximum_cdf_error,
          original_native_output_not_relabelled_as_projected=True)
    (work_dir / "NATIVE_RECEIPTS.json").write_text(json.dumps(raw_native, indent=2, allow_nan=False) + "\n")
    manifest = {str(path.relative_to(work_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(work_dir.rglob("*")) if path.is_file()}
    (work_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"schema": "hepta.quantized-guard.independent-validation.v1", "passed": all(row["passed"] for row in checks),
            "checks": checks, "total_checks": len(checks), "native_evidence_directory": str(work_dir),
            "native_evidence_manifest_sha256": hashlib.sha256((work_dir / "MANIFEST.json").read_bytes()).hexdigest(),
            "native_receipts": len(raw_native), "elapsed_ns": time.perf_counter_ns() - began,
            "implementation_source_sha256": hashlib.sha256(Path(__file__).with_name("quantized_guard.py").read_bytes()).hexdigest(),
            "validation_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "no_confirmation_data_used": True,
            "scope": "Q24 density and categorical guards with exact native roundtrip on the native-domain intersection; no task superiority or production promotion"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--native-dir", type=Path, default=Path(__file__).resolve().parent.parent / "evidence/native")
    args = parser.parse_args()
    work = args.work_dir or Path(tempfile.mkdtemp(prefix="aen-quantized-guard-parent-")) / "evidence"
    result = validate(work, args.native_dir)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": result["total_checks"],
                      "failures": [row["name"] for row in result["checks"] if not row["passed"]],
                      "native_evidence_directory": result["native_evidence_directory"]}))
    raise SystemExit(0 if result["passed"] else 1)
