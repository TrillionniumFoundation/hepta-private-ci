"""Independent continuous first-hit spectrum and measured grid error/cost.

Reference: backward PDE S_t=D S_xx+mu S_x, S_x(lower)=0, S(upper)=0.
The gauge transform has Robin/Dirichlet eigenfunctions. This is independent of
both finite generator construction and the earlier inverse-Laplace reference.
The optional central/face grid is a separate numerical candidate, not deployed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.linalg import expm
from scipy.optimize import brentq

from .finite import _parameters, generator

HERE = Path(__file__).resolve().parent


def spectral_first_hit(theta, driver, duration, terms):
    _, _, mu, sigma, boundary, reset, _ = _parameters(theta, driver, 3)
    length, position = boundary+1., reset+1.
    alpha, diffusion = mu/sigma**2, sigma**2/2
    # tan(kL)=-k/alpha; all roots are bracketed separately for alpha>0.
    k = np.array([brentq(lambda z: z*np.cos(z)+alpha*length*np.sin(z),
                         (j+.5)*np.pi, (j+1)*np.pi)/length for j in range(terms)])
    norm = (length/2*(1+alpha**2/k**2)+np.sin(2*k*length)/(4*k)*(1-alpha**2/k**2)
            +alpha*np.sin(k*length)**2/k**2)
    coefficients = (np.exp(alpha*(length-position)-diffusion*(k*k+alpha*alpha)*duration)
                    *np.sin(k*length)/k/norm
                    *(np.cos(k*position)+alpha/k*np.sin(k*position)))
    survival = float(np.sum(coefficients))
    if not np.isfinite(survival) or not -1e-11 <= survival <= 1+1e-11:
        raise ArithmeticError("Unresolved spectral first-hit probability")
    return 1-survival


def central_face(theta, driver, nodes):
    """Nonnegative centered drift, absorbing upper face at its actual location.

This is a different finite generator from the deployed upwind profile. It only
exists when cell Peclet <=1. Positivity is tested without clipping rates.
"""
    q, origin, _, _ = generator(theta, driver, nodes)
    _, _, mu, sigma, boundary, _, _ = _parameters(theta, driver, nodes)
    h = (boundary+1)/nodes
    up, down = sigma**2/(2*h*h)+mu/(2*h), sigma**2/(2*h*h)-mu/(2*h)
    if down < 0:
        raise ValueError("Centered rates violate positivity")
    q[:nodes, :] = 0.
    for i in range(nodes):
        if i:
            q[i, i-1], q[i, i] = down, -down
        rate = up if i < nodes-1 else 2*up
        q[i, i+1 if i < nodes-1 else nodes+1] = rate
        q[i, i] -= rate
    q[nodes-1, -1] = 2*up
    return q, origin


def measure(theta, driver, duration, nodes, scheme):
    prepare = time.process_time()
    if scheme == "native_upwind":
        q, origin, _, _ = generator(theta, driver, nodes)
    else:
        q, origin = central_face(theta, driver, nodes)
    generator_cpu = time.process_time()-prepare
    p0 = np.r_[origin, 0.]
    killed = q.copy()
    killed[nodes-1, nodes+1] = 0.
    times, first, count, mass = [], None, None, None
    for _ in range(7):
        cpu = time.process_time()
        propagated = p0 @ expm(q*duration)
        first = float((p0 @ expm(killed*duration))[-1])
        times.append(time.process_time()-cpu)
        count, mass = float(propagated[-1]), float(propagated[:-1].sum())
    _, _, mu, sigma, boundary, _, _ = _parameters(theta, driver, nodes)
    return dict(nodes=nodes, scheme=scheme, first_hit=first, expected_count=count,
                probability_mass=mass, generator_cpu_seconds=generator_cpu,
                full_count_and_first_hit_cpu_seconds=times,
                median_cpu_seconds=float(np.median(times)),
                probability_state_bytes=(nodes+2)*8, augmented_matrix_bytes=int(q.nbytes),
                upwind_extra_variance_ratio=mu*(boundary+1)/nodes/sigma**2 if scheme == "native_upwind" else 0.,
                measured_runtime="Python/SciPy float64 dense expm, one BLAS thread; not native or energy")


def main(args):
    wall, cpu = time.perf_counter(), time.process_time()
    specs = [dict(name="baseline", theta=[0.]*6, driver=0., duration=3.),
        dict(name="changed_coefficients", theta=[.7, -.4, -.3, .5, -.6, .4], driver=.8, duration=3.),
        dict(name="short_horizon_tail", theta=[0.]*6, driver=0., duration=.25)]
    rows = []
    for spec in specs:
        theta = np.array(spec["theta"])
        references = [spectral_first_hit(theta, spec["driver"], spec["duration"], n) for n in (64, 128, 256)]
        if max(references)-min(references) > 1e-10:
            raise ArithmeticError("Spectral resolution not stable")
        ref = references[-1]
        grids = []
        for scheme, nodes in [("native_upwind", 3)]+[(s, n) for s in ("native_upwind", "central_face_candidate") for n in (32, 64, 128)]:
            row = measure(theta, spec["driver"], spec["duration"], nodes, scheme)
            row["first_hit_absolute_error"] = abs(row["first_hit"]-ref)
            row["first_hit_relative_error"] = abs(row["first_hit"]-ref)/ref if ref > 0 else None
            grids.append(row)
        rows.append(spec | dict(spectral_terms=[64, 128, 256], spectral_values=references, grids=grids))
    result = dict(schema="hcsn.finite-resolution.r11.v1", cases=rows,
        deployed_model="native_upwind_3_active_2_erlang", deployed_model_changed=False,
        centered_candidate_deployed=False, continuum_equivalence=False,
        numerical_reference="Robin/Dirichlet Sturm-Liouville first-hit series; positive drift only",
        validation="64/128/256 spectral terms agree; no interval arithmetic guarantee",
        scope="Constant coefficients, reflected lower wall, fixed upper boundary, initial reset state",
        not_established=["Uniform error bound over moving or learned boundaries",
                         "Continuous repeated-event distribution or all rewards",
                         "Native cost for refined grids", "Quality or energy advantage"],
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/"finite.py", Path(__file__).resolve())},
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps(dict(output=str(args.output), cases=len(rows), cpu_seconds=result["cpu_seconds"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
