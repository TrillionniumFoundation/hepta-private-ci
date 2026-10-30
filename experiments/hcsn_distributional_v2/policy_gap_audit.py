"""Check whether the analytic Brownian boundary also optimizes the finite grid.

This is a numerical limitation audit, not a boundary-training method. A sampled
policy with higher value establishes a lower bound on suboptimality; the best
sample is never labeled a certified global optimum. No content labels are read.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from experiments.hcsn_free_boundary_v1.oracle_torch import free_boundary
from .distribution_kernel import Grid, make_flow, initial_probability, finite_generator_values


CASES = [
    dict(name="central", mu=.1, sigma=.45, rho=.45, K=.525, r=-.1, tau=.75),
    dict(name="negative_drift", mu=-.28, sigma=.32, rho=.7, K=.65, r=-.25, tau=1.1),
    dict(name="positive_low_discount", mu=.48, sigma=.32, rho=.17, K=.38, r=-.25, tau=.35),
    dict(name="large_noise", mu=.3, sigma=.58, rho=.2, K=.38, r=.05, tau=.35),
    dict(name="negative_high_noise", mu=-.28, sigma=.58, rho=.2, K=.65, r=.05, tau=1.1),
]


def audit(output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.process_time()
    sources = [Path(__file__), Path(__file__).with_name("distribution_kernel.py"),
               Path("experiments/hcsn_free_boundary_v1/oracle_torch.py")]
    source = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    registration = dict(schema="hcsn-v2-policy-gap-registration.v1", cases=CASES,
                        cells=[8, 32, 128], sampled_boundaries=257,
                        boundary_interval="K+0.02 through K+2/kappa; analytic boundary appended exactly",
                        initial_pressure=0.0, lower=-2.0, refractory_stages=2,
                        source=source, content_labels_accessed=False)
    (output / "REGISTRATION.json").write_text(json.dumps(registration, indent=2) + "\n")
    records = []
    with torch.no_grad():
        for case in CASES:
            p = {key: torch.tensor(value, dtype=torch.float64)
                 for key, value in case.items() if key != "name"}
            effective_tau = 2 / p["rho"] * torch.log1p(p["rho"] * p["tau"] / 2)
            boundary = free_boundary(p["mu"], p["sigma"], p["rho"], p["K"], p["r"], effective_tau)
            kappa = (torch.sqrt(p["mu"]**2 + 2*p["rho"]*p["sigma"]**2) - p["mu"]) / p["sigma"]**2
            candidates = torch.cat((torch.linspace(float(p["K"] + .02),
                                    float(p["K"] + 2/kappa), 257, dtype=torch.float64),
                                    boundary.reshape(1)))
            for cells in registration["cells"]:
                flow = make_flow(p["mu"], p["sigma"], candidates, p["r"], p["tau"],
                                 grid=Grid(cells=cells, lower=-2., refractory_stages=2))
                probability = initial_probability(flow, 0.)
                result = finite_generator_values(flow, probability, p["rho"], p["K"])
                values = result["J_total"]
                selected = int(values.argmax())
                own = float(values[-1])
                improvement = float(values[selected] - values[-1])
                vectors = result["vectors"]
                obstacle_violation = float((vectors["active_G"][-1] - vectors["active_J"][-1]).clamp_min(0).max())
                records.append(dict(case=case["name"], cells=cells,
                    analytic_boundary=float(boundary), analytic_policy_value=own,
                    best_sampled_boundary=float(candidates[selected]),
                    best_sampled_value=float(values[selected]),
                    sampled_improvement_lower_bound=improvement,
                    relative_sampled_improvement=improvement/max(abs(own), 1e-15),
                    max_active_obstacle_violation=obstacle_violation,
                    candidate_boundaries=candidates.tolist(), candidate_values=values.tolist()))
    changed = [str(path) for path in sources if hashlib.sha256(path.read_bytes()).hexdigest() != source[str(path)]]
    result = dict(schema="hcsn-v2-policy-gap-audit.v1", records=records,
                  source_changed_during_audit=changed, self_cpu_through_cutoff=time.process_time()-started,
                  claim="Finite-generator own-policy evaluation does not imply this analytic boundary is finite-grid optimal",
                  limitations=["Sampled comparison is not a global optimization certificate",
                               "Finite lower reflection and spatial interpolation remain",
                               "Neither policy objective is a classification Bellman objective"])
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if changed:
        raise RuntimeError("Audit source changed during calculation")
    print(json.dumps({"cases":len(records), "largest_sampled_relative_improvement":max(x["relative_sampled_improvement"] for x in records),
                      "largest_obstacle_violation":max(x["max_active_obstacle_violation"] for x in records)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    audit(args.output)


if __name__ == "__main__":
    main()
