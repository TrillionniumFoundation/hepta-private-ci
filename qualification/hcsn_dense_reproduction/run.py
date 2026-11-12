"""Source-bound new execution of the two fixed profiles; never old raw recovery."""

import argparse
from fractions import Fraction
import hashlib
import inspect
import json
import os
from pathlib import Path
import resource
import sys
import time
import numpy as np
import scipy
from scipy.special import ndtr
from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_joint_dde.model import JointModel
from . import controlled_core, positive_phase, profile
from .positive_phase import phase_count
from .profile import NearDenseGenerator, ControlledModel


def reference(reset, time_value, order):
    nodes, weights = np.polynomial.legendre.leggauss(order)
    mu, sigma = -0.12, 0.35
    # All times in this fixed query are shorter than phase width or require
    # the correct active-duration lower limit after all initial phase release.
    lo = max(0.0, time_value - 0.025)
    duration = lo + (nodes + 1) * (time_value - lo) / 2
    root = sigma * np.sqrt(duration)
    cdf = ndtr((-reset - mu * duration) / root) + np.exp(
        -2 * mu * reset / sigma**2) * ndtr((-reset + mu * duration) / root)
    return float(np.dot(weights, cdf) * (time_value - lo) / (2 * 0.025))


def source_hashes():
    paths = {Path(__file__).resolve()}
    for obj in (Packet, GradedSpatialGenerator, GradedJointModel, JointModel,
                profile, controlled_core, positive_phase):
        paths.add(Path(inspect.getfile(obj)).resolve())
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--profile", choices=("near800", "near960"), required=True)
    parser.add_argument("--atol", type=float, required=True)
    parser.add_argument("--mode", choices=("positive", "dde"), required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    before = source_hashes()
    started, cpu = time.perf_counter(), time.process_time()
    near, edge, reset = ((800, 0.5, 0.32) if args.profile == "near800"
                         else (960, 0.48, 0.32725))
    spatial = NearDenseGenerator(1024, 8.0, -0.12, 0.35, 6.0, near, edge)
    model = ControlledModel(spatial, reset, 0.2, 0.15)
    times = np.array([0.001, 0.003, 0.02, 0.04, 0.08, 0.16])
    _, _, _, reset_weights = model.ingredients()
    down, up = spatial.rates
    positive = [phase_count(down, up, reset_weights, float(t)) for t in times]
    refs64 = np.array([reference(reset, float(t), 64) for t in times])
    refs128 = np.array([reference(reset, float(t), 128) for t in times])
    raw = {"time": times, "positive_M": np.array([r["M"] for r in positive]),
           "reference64_M": refs64, "reference128_M": refs128,
           "nodes": spatial.nodes, "down": down, "up": up, "reset": reset_weights}
    dde = None
    if args.mode == "dde":
        phase = (Packet("new-reproduction-initial-uniform", Fraction(0),
                        Fraction(1, 40), Fraction(1), (Fraction(-7, 10),)),)
        dde = model.solve(times, np.zeros(1025), np.zeros((1025, 1)), phase,
                          rtol=1e-12, atol=args.atol, max_step=0.0025)
        for key in ("active", "upper", "refractory", "events", "discounted_events",
                    "discounted_active_time", "discounted_remaining_phase",
                    "mass_residual", "content_residual"):
            raw["dde_" + key] = np.array([r[key] for r in dde["rows"]])
    after = source_hashes()
    np.savez_compressed(output / "RAW.npz", **raw)
    rows = []
    for i, t in enumerate(times):
        row = {"time": float(t), "positive": positive[i],
               "reference64": float(refs64[i]), "reference128": float(refs128[i]),
               "relative_reference_difference": float((refs64[i] - refs128[i]) / refs128[i]),
               "relative_report_floor": 1e-12,
               "relative_diagnostic_eligible": bool(refs128[i] >= 1e-12),
               "positive_relative_error": float((positive[i]["M"] - refs128[i]) / refs128[i])}
        if dde:
            value = float(raw["dde_events"][i, 0])
            row.update(dde_M=value, dde_relative_error=float((value - refs128[i]) / refs128[i]),
                       dde_minus_positive=value - positive[i]["M"])
        rows.append(row)
    summary = {"schema": "hcsn-neardense-new-reproduction-v1",
               "identity": "new source and new attempt after old raw loss; never recovered old receipt",
               "status": "HOLD_NO_GO", "all_closed": False, "prospective_scientific_gate": False,
               "profile": args.profile, "near_intervals": near, "near_endpoint": edge,
               "total_intervals": 1024, "endpoint": 8, "reset": reset,
               "mode": args.mode, "atol": args.atol, "rtol": 1e-12, "max_step": 0.0025,
               "rows": rows, "source_sha256_before": before, "source_sha256_after": after,
               "source_unchanged": before == after,
               "internal_steps": dde["internal_steps"] if dde else None,
               "wall_seconds": time.perf_counter() - started,
               "cpu_seconds": time.process_time() - cpu,
               "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "versions": {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__},
               "thread_environment": {k: os.environ.get(k) for k in
                                      ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")},
               "raw_sha256": hashlib.sha256((output / "RAW.npz").read_bytes()).hexdigest(),
               "limitations": ["post-failure exposed profiles; no new admission",
                               "Poisson bound excludes roundoff and continuum error",
                               "upper escape permanently active nonreturning",
                               "no full old-state trajectory or training replay",
                               "no new-profile gradients or performance advantage",
                               "right-tail value cost remains separately required"]}
    (output / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("profile", "mode", "source_unchanged",
                                            "internal_steps", "wall_seconds", "raw_sha256")}))
    if not summary["source_unchanged"]:
        raise RuntimeError("source changed during execution")


if __name__ == "__main__":
    main()
