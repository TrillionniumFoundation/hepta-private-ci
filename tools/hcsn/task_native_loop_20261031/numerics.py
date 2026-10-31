"""Connect trained finite cells to independent reflected-continuum references.

The Laplace BVP has a reflecting lower wall and an absorbing upper wall, exactly
the declared spatial boundary conditions of the native finite cell. Its renewal
law includes two Erlang recovery phases. Numerical inverse Laplace transforms
are checked at two precisions; they are not interval-arithmetic certificates.
The imported scalar QVI has a different reward/domain and is labeled separately.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import time

import mpmath as mp
import numpy as np
from scipy.sparse import coo_matrix, eye
from scipy.sparse.linalg import expm_multiply, spsolve

from ..task_value_factorial_20261030.cells import physical
from ..task_value_factorial_20261030.propagation import flow
from experiments.hcsn_hx_unified_v3.qvi_grid_independent import solve_regenerative_grid
from experiments.hcsn_hx_unified_v3.test_qvi_grid_independent import analytic_reference

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GRIDS = (3, 6, 12, 48, 192)


def transform(cell, s, start=None):
    """E_x exp(-s*tau_b), solving sigma²u''/2+mu*u'=s*u, u'(a)=0,u(b)=1."""
    mu, sigma, lower, upper, reset = [mp.mpf(str(x)) for x in
        (cell.drift, cell.sigma, cell.lower, cell.boundary, cell.reset)]
    x = reset if start is None else mp.mpf(str(start))
    alpha = mu / sigma**2
    beta = mp.sqrt(alpha**2 + 2*s/sigma**2)

    def fundamental(distance):
        return mp.exp(-alpha*distance)*(mp.cosh(beta*distance) + alpha*mp.sinh(beta*distance)/beta)

    return fundamental(x-lower) / fundamental(upper-lower)


def continuum(cell, duration, degree):
    with mp.workdps(max(60, degree*2)):
        time_arg = mp.mpf(str(duration))
        recovery_rate = 2/mp.mpf(str(cell.refractory))

        def renewal_transform(s):
            phi = transform(cell, s)
            recovery = (recovery_rate/(recovery_rate+s))**2
            return phi/(s*(1-phi*recovery))

        first = mp.invertlaplace(lambda s: transform(cell, s)/s, time_arg, method="dehoog", degree=degree)
        count = mp.invertlaplace(renewal_transform, time_arg, method="dehoog", degree=degree)
        discount = mp.mpf('.12')
        phi = transform(cell, discount)
        discounted = phi/(1-phi*(recovery_rate/(recovery_rate+discount))**2)
        return dict(first_hit=float(first), expected_count=float(count), discounted_event_count=float(discounted))


def finite(cell, duration, nodes):
    """Independent sparse spatial discretization, preserving the native upwind law."""
    h = (cell.boundary-cell.lower)/nodes
    up = cell.sigma**2/(2*h*h) + max(cell.drift, 0)/h
    down = cell.sigma**2/(2*h*h) + max(-cell.drift, 0)/h
    reset = (cell.reset-cell.lower)/h-.5
    index = int(math.floor(reset))
    if not 0 <= index < nodes-1:
        raise ValueError("Reset outside interpolation centers")
    left = index+1-reset
    source, target, values = [], [], []

    def edge(i, j, rate):
        source.extend((i, i))
        target.extend((j, i))
        values.extend((rate, -rate))

    for i in range(nodes):
        if i:
            edge(i, i-1, down)
        edge(i, i+1 if i+1 < nodes else nodes+1, up)
    rate = 2/cell.refractory
    edge(nodes+1, nodes, rate)
    edge(nodes, index, rate*left)
    edge(nodes, index+1, rate*(1-left))
    q = coo_matrix((values, (source, target)), shape=(nodes+3, nodes+3)).tolil()
    q[nodes-1, nodes+2] = up
    p = np.zeros(nodes+3)
    p[index], p[index+1] = left, 1-left
    result = expm_multiply(duration*q.tocsr().T, p)
    killed = q.copy()
    killed[nodes-1, nodes+1] = 0.
    first = expm_multiply(duration*killed.tocsr().T, p)[-1]
    reward = np.zeros(nodes+2)
    reward[nodes-1] = up
    value = spsolve(.12*eye(nodes+2)-q[:nodes+2, :nodes+2].tocsr(), reward)
    return dict(first_hit=float(first), expected_count=float(result[-1]),
                discounted_event_count=float(p[:-1]@value), active_nodes=nodes,
                mass_error=float(result[:-1].sum()-1),
                artificial_variance_ratio=abs(cell.drift)*h/cell.sigma**2)


def finite_frechet(cell, duration, epsilon=1e-5):
    """Include the reset interpolation derivative, not just the exponential."""
    result = {}
    for name in ("drift", "sigma", "boundary", "reset", "refractory"):
        plus = replace(cell, **{name: getattr(cell, name)+epsilon})
        minus = replace(cell, **{name: getattr(cell, name)-epsilon})
        numeric = (finite(plus, duration, cell.active)["expected_count"]-
                   finite(minus, duration, cell.active)["expected_count"])/(2*epsilon)
        _, count, _, dcount = flow((cell,), duration, directions=({name: 1.},))

        def origin(c):
            h = (c.boundary-c.lower)/c.active
            value = (c.reset-c.lower)/h-.5
            index = int(math.floor(value))
            p = np.zeros(c.active+c.phases)
            p[index], p[index+1] = index+1-value, value-index
            return p

        dp = (origin(plus)-origin(minus))/(2*epsilon)
        deriv = float(origin(cell)@dcount[:, 0] + dp@count[:, 0])
        result[name] = dict(frechet=deriv, independent_difference=numeric, absolute_error=abs(deriv-numeric))
    return result


def qvi_rows(cell):
    # Only the recovery Laplace transform enters this stationary scalar QVI.
    # The equivalent deterministic delay is not an equivalence of event-time laws.
    rho = .12
    tau = 2*math.log1p(rho*cell.refractory/2)/rho
    boundary, value = analytic_reference(cell.drift, cell.sigma, rho, 1., cell.reset, tau, 0.)
    rows = []
    for nodes in (301, 601, 1201):
        kwargs = dict(drift=float(cell.drift), diffusion=float(cell.sigma), discount=rho, cost=1., reset=float(cell.reset),
                      refractory=tau, lower=-26., upper=21., nodes=nodes)
        grid = solve_regenerative_grid(**kwargs)
        epsilon = 1e-4
        grid_derivative = (solve_regenerative_grid(**(kwargs | {"drift": cell.drift+epsilon})).at(0.)-
                           solve_regenerative_grid(**(kwargs | {"drift": cell.drift-epsilon})).at(0.))/(2*epsilon)
        exact_derivative = (analytic_reference(cell.drift+epsilon, cell.sigma, rho, 1., cell.reset, tau, 0.)[1]-
                            analytic_reference(cell.drift-epsilon, cell.sigma, rho, 1., cell.reset, tau, 0.)[1])/(2*epsilon)
        rows.append(dict(nodes=nodes, spacing=grid.grid_step, boundary=grid.threshold, value=grid.at(0.),
                         boundary_error=abs(grid.threshold-boundary), value_error=abs(grid.at(0.)-value),
                         drift_gradient_error=abs(grid_derivative-exact_derivative),
                         discrete_residual=grid.bellman_residual))
    return dict(equivalent_discount_delay=tau, analytic_boundary=boundary, analytic_value=value, grids=rows)


def main(args):
    started, cpu = time.perf_counter(), time.process_time()
    freeze = json.loads((args.training/"FREEZE.json").read_text())
    cases = []
    base = physical(np.zeros(11), 0.)
    for name, cell, duration in (("registered", base, 3.),
        ("low_noise", replace(base, sigma=.03), 3.),
        ("short_recovery", replace(base, refractory=.01), 3.),
        ("tail", base, .25)):
        cases.append((name, cell, duration, None))
    for name, receipt in freeze["policies"].items():
        if not name.endswith("_analytic_value.json"):
            continue
        path = args.training/name
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]:
            raise ValueError("Frozen model changed")
        model = json.loads(path.read_text())
        cases.append((name, physical(model["parameters"], 0.), 3., receipt["sha256"]))
    results = []
    for name, cell, duration, model_hash in cases:
        coarse, reference = continuum(cell, duration, 40), continuum(cell, duration, 72)
        resolution = []
        for nodes in GRIDS:
            item = finite(cell, duration, nodes)
            item["absolute_error"] = {k: abs(item[k]-reference[k]) for k in reference}
            resolution.append(item)
        item = dict(case=name, parameters=vars(cell), duration=duration, model_sha256=model_hash,
                    continuum=reference, inverse_laplace_precision_difference={k: abs(reference[k]-coarse[k]) for k in reference},
                    grids=resolution, native_grid_frechet=finite_frechet(cell, duration),
                    scalar_stationary_qvi=qvi_rows(cell) if model_hash is not None else None)
        results.append(item)
        print(json.dumps(dict(case=name, native_first_hit_error=resolution[0]["absolute_error"]["first_hit"],
                              refined_first_hit_error=resolution[-1]["absolute_error"]["first_hit"])), flush=True)
    source = [Path(__file__).resolve(), REPO/"experiments/hcsn_hx_unified_v3/qvi_grid_independent.py",
              REPO/"experiments/hcsn_hx_unified_v3/test_qvi_grid_independent.py",
              REPO/"tools/hcsn/task_value_factorial_20261030/propagation.py",
              REPO/"tools/hcsn/round9_20261031/native/src/cell.rs"]
    result = dict(schema="hcsn.task.native.loop.numerics.v1", cases=results,
        source_sha256={str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source},
        training_freeze_sha256=hashlib.sha256((args.training/"FREEZE.json").read_bytes()).hexdigest(),
        independent_qvi_import="979dc20082f30c88b17e7b9c92ec81108574e5ee",
        mpmath_version=mp.__version__, cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-started,
        continuous_native_equivalence=False,
        limitations=["Independent inverse Laplace numerical reference, no interval certificate",
          "Native remains three spatial bins plus two Erlang phases; refinement is diagnostic only",
          "Stationary scalar QVI uses x-K impulse reward and an unbounded-domain analytic reference, not the packet-task Bellman law",
          "Static learned-coefficient probes do not validate arbitrary moving boundaries or all histories"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
