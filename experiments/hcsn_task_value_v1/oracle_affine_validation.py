"""Independent spatial QVI for operators.py's affine-running-reward family.

The finite-difference solver uses explicit Erlang phase states and never calls
the analytic boundary/root. It optimizes every interior grid state's action.
This is a one-dimensional frozen-task contract, not a classification optimum.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import brentq
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve


@dataclass(frozen=True)
class Affine:
    mu: float = .1
    sigma: float = .45
    rho: float = .45
    cost: float = .525
    reset: float = -.1
    tau: float = .75
    slope: float = -.0275
    stages: int = 2

    def validate(self):
        continuous = (self.mu, self.sigma, self.rho, self.cost,
                      self.reset, self.tau, self.slope)
        if not all(math.isfinite(z) for z in continuous):
            raise ValueError("Nonfinite affine contract")
        if min(self.sigma, self.rho, self.tau) <= 0 or self.slope >= self.rho:
            raise ValueError("Require sigma,rho,tau>0 and slope<rho")
        if type(self.stages) is not int or not 1 <= self.stages <= 32:
            raise ValueError("Invalid refractory stages")


def closed_form(p, x):
    p.validate()
    scale = math.sqrt(p.mu*p.mu+2*p.rho*p.sigma*p.sigma)
    kappa = 2*p.rho/(scale+p.mu) if p.mu >= 0 else (scale-p.mu)/p.sigma**2
    delay = (1+p.rho*p.tau/p.stages)**(-p.stages)
    amplitude = 1-p.slope/p.rho
    particular = lambda state: p.slope*np.asarray(state)/p.rho+p.slope*p.mu/p.rho**2
    effective = (p.cost+particular(0.)-delay*particular(p.reset))/amplitude
    if not effective > p.reset:
        raise ValueError("This oracle covers the effective_cost > reset upper-boundary family")
    residual = lambda b: kappa*(b-effective)+delay*math.exp(-kappa*(b-p.reset))-1
    boundary = brentq(residual, effective, effective+1/kappa, xtol=1e-14)
    reset_value = float(particular(p.reset)+amplitude/kappa*math.exp(-kappa*(boundary-p.reset)))
    state = np.asarray(x, dtype=float)
    below = state < boundary
    values = state-p.cost+delay*reset_value
    values = np.where(below, particular(state)+amplitude/kappa*
                      np.exp(kappa*np.minimum(state-boundary, 0)), values)
    phase = np.array([(1+p.rho*p.tau/p.stages)**(-(p.stages-j))*reset_value
                      for j in range(p.stages)])
    return {"boundary": boundary, "reset_value": reset_value, "values": values,
            "phases": phase, "kappa": kappa, "delay": delay,
            "effective_cost": effective, "smooth_fit_residual": residual(boundary)}


def finite_difference(p, *, spacing=.05, lower=-8., upper=3.):
    """Independent Howard solve with affine far-left and immediate-fire far-right.

    The lower Dirichlet value is U(lower), the asymptotic particular solution;
    its truncation error is checked by separately moving the lower boundary.
    No analytic free boundary or analytic phase/reset value is inserted.
    """
    p.validate()
    if not 0 < spacing <= .5 or not lower < p.reset < upper:
        raise ValueError("Invalid finite-difference domain")
    n = int(round((upper-lower)/spacing))+1
    if not 20 <= n <= 10000 or abs((n-1)*spacing-(upper-lower)) > 1e-10:
        raise ValueError("Domain must contain an integral, bounded number of intervals")
    x = np.linspace(lower, upper, n)
    diffusion = p.sigma**2/(2*spacing**2)
    down, up = diffusion-p.mu/(2*spacing), diffusion+p.mu/(2*spacing)
    if min(down, up) <= 0:
        raise ValueError("Centered discretization requires positive jump rates")
    lam = p.stages/p.tau
    idx = min(int(np.searchsorted(x, p.reset)-1), n-2)
    weight = (p.reset-x[idx])/spacing
    policy = np.zeros(n, dtype=np.int8)
    policy[0], policy[-1] = 2, 1
    for iteration in range(1, 250):
        matrix = lil_matrix((n+p.stages, n+p.stages))
        rhs = np.zeros(n+p.stages)
        for i, action in enumerate(policy):
            if action == 2:
                matrix[i, i] = 1
                rhs[i] = p.slope*x[i]/p.rho+p.slope*p.mu/p.rho**2
            elif action == 1:
                matrix[i, i], matrix[i, n] = 1, -1
                rhs[i] = x[i]-p.cost
            else:
                matrix[i, i] = p.rho+down+up
                matrix[i, i-1], matrix[i, i+1] = -down, -up
                rhs[i] = p.slope*x[i]
        for stage in range(p.stages):
            row = n+stage
            matrix[row, row] = p.rho+lam
            if stage < p.stages-1:
                matrix[row, row+1] = -lam
            else:
                matrix[row, idx] = -lam*(1-weight)
                matrix[row, idx+1] = -lam*weight
        values = spsolve(matrix.tocsc(), rhs)
        wait = (p.slope*x[1:-1]+down*values[:n-2]+up*values[2:n])/(p.rho+down+up)
        fire = x[1:-1]-p.cost+values[n]
        proposed = policy.copy()
        old = np.where(policy[1:-1] == 0, wait, fire)
        best = np.maximum(wait, fire)
        proposed[1:-1] = np.where(best > old+1e-13, (fire > wait).astype(np.int8), policy[1:-1])
        if np.array_equal(proposed, policy):
            wait_residual = (p.slope*x[1:-1]+down*(values[:n-2]-values[1:n-1])+
                             up*(values[2:n]-values[1:n-1])-p.rho*values[1:n-1])
            fire_residual = fire-values[1:n-1]
            residual = float(np.max(np.abs(np.maximum(wait_residual, fire_residual))))
            exercise = np.flatnonzero(policy == 1)
            return {"x": x, "values": values[:n], "phases": values[n:],
                    "policy": policy, "iterations": iteration,
                    "first_fire": float(x[exercise[0]]), "qvi_residual": residual,
                    "reset_value": float(np.interp(p.reset, x, values[:n]))}
        policy = proposed
    raise RuntimeError("Affine spatial QVI failed to converge")


def run():
    p = Affine()
    path = Path(__file__).parent/"results"/"oracle001"
    path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report = {"schema": "affine-running-task-qvi-v1", "contract": vars(p),
              "scope": "continuous 1D frozen-task upper-boundary family; independent Erlang phase QVI",
              "runs": [], "failures": []}
    try:
        exact = closed_form(p, np.array([p.reset]))
        report["analytic"] = {k: float(v) for k, v in exact.items() if k not in ("values", "phases")}
        for spacing in (.2, .1, .05, .025, .0125, .00625):
            numeric = finite_difference(p, spacing=spacing)
            reference = closed_form(p, numeric["x"])
            report["runs"].append({"spacing": spacing,
                "max_value_error": float(np.max(np.abs(numeric["values"]-reference["values"]))),
                "phase_error": float(np.max(np.abs(numeric["phases"]-reference["phases"]))),
                "first_fire": numeric["first_fire"],
                "boundary_error": abs(numeric["first_fire"]-exact["boundary"]),
                "qvi_residual": numeric["qvi_residual"], "iterations": numeric["iterations"]})
        wide = finite_difference(p, spacing=.00625, lower=-12.)
        report["lower_domain_extension_reset_difference"] = abs(wide["reset_value"]-numeric["reset_value"])
        eps = 2e-5
        report["gradient_checks"] = []
        for name in ("mu", "sigma", "rho", "cost", "reset", "tau", "slope"):
            positive = replace(p, **{name: getattr(p, name)+eps})
            negative = replace(p, **{name: getattr(p, name)-eps})
            analytic_derivative = (closed_form(positive, 0.)["reset_value"]-
                                   closed_form(negative, 0.)["reset_value"])/(2*eps)
            spatial_derivative = (finite_difference(positive, spacing=.00625)["reset_value"]-
                                  finite_difference(negative, spacing=.00625)["reset_value"])/(2*eps)
            coarse_derivative = (finite_difference(positive, spacing=.025)["reset_value"]-
                                 finite_difference(negative, spacing=.025)["reset_value"])/(2*eps)
            report["gradient_checks"].append({"parameter": name,
                "analytic_reset_value_derivative": analytic_derivative,
                "spatial_qvi_reset_value_derivative": spatial_derivative,
                "spatial_gradient_spacing": .00625,
                "coarse_gradient_error_h_0_025": abs(analytic_derivative-coarse_derivative),
                "error": abs(analytic_derivative-spatial_derivative)})
        runs = report["runs"]
        checks = [runs[-1]["max_value_error"] < 1e-5,
                  runs[-1]["max_value_error"] < runs[0]["max_value_error"],
                  runs[-1]["boundary_error"] < .05,
                  all(r["qvi_residual"] < 1e-9 for r in runs),
                  report["lower_domain_extension_reset_difference"] < 2e-6,
                  max(r["error"] for r in report["gradient_checks"]) < .001]
        if not all(checks):
            report["failures"].append({"checks": checks})
    except Exception as exc:
        report["failures"].append({"exception": type(exc).__name__, "message": str(exc)})
    report["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["passed"] = not report["failures"]
    destination = path/f"affine_{stamp}.json"
    destination.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"report": str(destination), "passed": report["passed"],
                      "failures": report["failures"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
