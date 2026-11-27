"""Fixed-profile positive phase sweep; new identity after #6224.

Post-failure development only. No mesh selection, future task, DDE or training.
"""

import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path
import resource
import sys
import time
import numpy as np
import scipy
from scipy.special import gammainc, gammaincc, ndtr
from qualification.hcsn_dense_reproduction.profile import NearDenseGenerator, ControlledModel
from qualification.hcsn_dense_reproduction.positive_phase import phase_count
from qualification.hcsn_dense_reproduction import controlled_core
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_joint_dde.model import JointModel


def node_phase_counts(down, up, horizon, width=0.025):
    """All initial-node event masses via the positive backward Markov series."""
    down, up = np.asarray(down), np.asarray(up)
    if (down.ndim != 1 or up.shape != down.shape or not len(down)
            or np.min(np.r_[down, up]) < 0
            or not np.all(np.isfinite(np.r_[down, up]))
            or not 0 < horizon <= 0.2 or not 0 < width <= 0.2):
        raise ValueError("bounded positive first-cycle geometry/time required")
    nu = float(np.nextafter(np.max(down + up), np.inf))
    if nu <= 0:
        raise ValueError("strictly positive jump-rate bound required")
    lo, hi, lam = max(0, horizon - width), horizon, nu * horizon
    cutoff = math.ceil(lam + 14 * math.sqrt(lam) + 100)
    if cutoff > 500000:
        raise ValueError("fixed term budget exceeded")
    k = np.arange(cutoff + 1)
    low_tail, high_tail = gammainc(k + 1, nu * lo), gammainc(k + 1, nu * hi)
    coefficients = np.where(low_tail > 0.5,
                            gammaincc(k + 1, nu * lo) - gammaincc(k + 1, nu * hi),
                            high_tail - low_tail) / (nu * width)
    if coefficients.min() < 0 or not np.all(np.isfinite(coefficients)):
        raise ArithmeticError("phase coefficient positivity unresolved")
    stay, left, right = 1 - (down + up) / nu, down / nu, up / nu
    if stay.min() < 0:
        raise ArithmeticError("uniformization transition positivity unresolved")
    power = np.r_[1.0, np.zeros(len(down) + 1)]
    total, compensation = np.zeros_like(power), np.zeros_like(power)
    minimum, maximum = 0.0, 1.0
    for c in coefficients:
        term = c * power - compensation
        value = total + term
        compensation = (value - total) - term
        total = value
        power[1:-1] = stay * power[1:-1] + left * power[:-2] + right * power[2:]
        minimum = min(minimum, float(power.min()))
        maximum = max(maximum, float(power.max()))
    return total, {"nu": nu, "terms": cutoff + 1,
                   "truncation_bound": hi * float(gammainc(cutoff + 1, lam)) / width,
                   "minimum_power_probability": minimum,
                   "maximum_power_probability": maximum,
                   "roundoff_certified": False}


def continuum(reset_values, t, mu, sigma, order):
    nodes, weights = np.polynomial.legendre.leggauss(order)
    lo = max(0.0, t - 0.025)
    duration = lo + (nodes + 1) * (t - lo) / 2
    x = np.asarray(reset_values)[:, None]
    sd = sigma * np.sqrt(duration)
    cdf = ndtr((-x - mu * duration) / sd) + np.exp(-2 * mu * x / sigma**2) * ndtr(
        (-x + mu * duration) / sd)
    return cdf @ weights * (t - lo) / (2 * 0.025)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    paths = sorted(args.journals.glob("seed*-*/training.jsonl"))
    if len(paths) != 12:
        raise ValueError("all twelve original journals required")
    sources = {Path(__file__).resolve()}
    for obj in (NearDenseGenerator, ControlledModel, phase_count, GradedSpatialGenerator,
                GradedJointModel, JointModel, controlled_core):
        sources.add(Path(inspect.getfile(obj)).resolve())
    before = {str(p): digest(p) for p in sorted(sources)}
    summary_path = args.journals / "SUMMARY.json"
    if digest(summary_path) != "c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715":
        raise ValueError("original artifact SUMMARY identity changed")
    original_summary = json.loads(summary_path.read_text())
    expected_journals = {
        str(args.journals / ("seed" + str(r["seed"]) + "-" + r["arm"]) / "training.jsonl"):
        r["training_trace_sha256"] for r in original_summary["runs"]}
    input_before = {str(p): digest(p) for p in paths}
    if input_before != expected_journals:
        raise ValueError("original journal SHA identities changed")
    input_before[str(summary_path)] = digest(summary_path)
    started, cpu = time.perf_counter(), time.process_time()
    physics, count, valid_count = set(), 0, 0
    for path in paths:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if "states" not in row:
                continue
            p = row["physical_parameters"]
            physics.add(tuple(p[name] for name in
                              ("mu", "sigma", "absolute_reset", "log_boundary", "discount")))
            count += len(row["states"])
            valid_count += int(np.asarray(row["valid_mask"], dtype=bool).sum())
    if count != 14336 or valid_count != 14336 or len(physics) != 184:
        raise ValueError("original position/physics coverage changed")
    ordered = sorted(physics)
    fixed = {(p[0], p[1], p[2], p[4]) for p in ordered}
    if len(fixed) != 1:
        raise ValueError("this fixed-physics sweep cannot claim varying parameters")
    mu, sigma, absolute_reset, discount = next(iter(fixed))
    original_resets = sorted({math.log(p[2]) - p[3] for p in ordered})
    resets = np.asarray(sorted(set(original_resets) | {0.32, 0.327, 0.32025, 0.32725}))
    times = np.asarray([0.001, 0.003, 0.02, 0.04, 0.08, 0.16])
    ref64 = np.asarray([continuum(resets, t, mu, sigma, 64) for t in times])
    ref128 = np.asarray([continuum(resets, t, mu, sigma, 128) for t in times])
    raw = {"resets": resets, "times": times, "reference64_M": ref64,
           "reference128_M": ref128,
           "original_reset": np.asarray([r in original_resets for r in resets])}
    panels = []
    for name, near, edge in (("near800", 800, 0.5), ("near960", 960, 0.48)):
        spatial = NearDenseGenerator(1024, 8.0, mu, sigma, 6.0, near, edge)
        down, up = spatial.rates
        values, bounds, metadata = [], [], []
        for t in times:
            nodes, report = node_phase_counts(down, up, float(t))
            values.append(np.interp(resets, spatial.nodes, nodes))
            bounds.append(report["truncation_bound"])
            metadata.append(report)
        values = np.asarray(values)
        # Independent orientation check against the retained forward-row algorithm.
        crosschecks = []
        for reset in (0.32, 0.32725):
            model = ControlledModel(spatial, reset, 0.2, discount)
            reset_weights = model.ingredients()[-1]
            for t in (0.02, 0.16):
                forward = phase_count(down, up, reset_weights, t)
                i = int(np.flatnonzero(times == t)[0])
                j = int(np.flatnonzero(resets == reset)[0])
                crosschecks.append({"reset": reset, "time": t,
                                    "forward_M": forward["M"],
                                    "backward_M": float(values[i, j]),
                                    "absolute_difference": abs(forward["M"] - values[i, j])})
        raw[name + "_M"] = values
        raw[name + "_truncation_bound"] = np.asarray(bounds)
        raw[name + "_nodes"] = spatial.nodes
        rows = []
        for i, t in enumerate(times):
            eligible = ref128[i] >= 1e-12
            relative = np.abs(values[i] - ref128[i]) / ref128[i]
            worst = int(np.argmax(np.where(eligible, relative, -np.inf))) if eligible.any() else None
            rows.append({"time": float(t), "relative_reference_floor": 1e-12,
                         "eligible_rows": int(eligible.sum()),
                         "below_floor_rows": int((~eligible).sum()),
                         "maximum_eligible_relative_M": float(relative[worst]) if worst is not None else None,
                         "worst_reset": float(resets[worst]) if worst is not None else None,
                         "maximum_absolute_M": float(np.max(np.abs(values[i] - ref128[i])))})
        panels.append({"profile": name, "rows": rows, "series": metadata,
                       "forward_backward_crosschecks": crosschecks})
    np.savez_compressed(args.output / "RAW.npz", **raw)
    after = {str(p): digest(p) for p in sorted(sources)}
    input_after = {p: digest(p) for p in input_before}
    result = {"schema": "hcsn-fixed-dense-reset-sweep-v1", "status": "HOLD_NO_GO",
              "all_closed": False, "prospective_gate": False,
              "source_base": "2e04c22b7860320127a9efe3a83c57654adf788d",
              "fixed_profiles_not_tuned": True, "parameters": {
                  "mu": mu, "sigma": sigma, "absolute_reset": absolute_reset, "discount": discount},
              "original_positions": count, "original_physics": len(physics),
              "original_resets": len(original_resets), "resets_with_supplemental": len(resets),
              "panels": panels, "source_sha256_before": before, "source_sha256_after": after,
              "input_sha256_before": input_before, "input_sha256_after": input_after,
              "source_and_inputs_unchanged": before == after and input_before == input_after,
              "raw_sha256": digest(args.output / "RAW.npz"),
              "wall_seconds": time.perf_counter() - started,
              "cpu_seconds": time.process_time() - cpu,
              "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "versions": {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__},
              "new_dde_runs": 0, "new_training_runs": 0,
              "limitations": ["post-failure exposed reset sweep, no new scientific admission",
                              "phase U[0,.025] only, first-cycle horizon <=.16<delay",
                              "no relative qualification below fixed 1e-12 reference floor",
                              "no time below .001 or finite horizon above .16",
                              "no physical-parameter box coverage",
                              "Poisson bound excludes floating point roundoff",
                              "no actual old-state rollout or gradient qualification"]}
    (args.output / "SUMMARY.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"panels": panels, "raw_sha256": result["raw_sha256"],
                      "wall_seconds": result["wall_seconds"]}))
    if not result["source_and_inputs_unchanged"]:
        raise RuntimeError("source or original journal changed")


if __name__ == "__main__":
    main()
