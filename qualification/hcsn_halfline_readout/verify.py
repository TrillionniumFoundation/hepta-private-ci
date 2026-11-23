"""Recompute the continuous first-passage readout at the two original split meshes."""
import argparse
import hashlib
import importlib
import json
import math
import platform
import sys
from pathlib import Path

import mpmath as mp
import numpy as np
import scipy
import torch
from scipy.linalg import expm

from qualification.hcsn_differentiable.operator import _first_hit_logprob
from qualification.hcsn_regenerative.tensor import TensorDiffusion
from qualification.hcsn_split_mesh import test_split

PROTOCOL = Path(__file__).with_name("protocol.json")
PLAN = json.loads(PROTOCOL.read_text())
GATE = PLAN["gates"]


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify_source():
    roots = {}
    for name in ("hcsn_differentiable", "hcsn_regenerative", "hcsn_split_mesh"):
        module = importlib.import_module(f"qualification.{name}")
        roots[name] = Path(next(iter(module.__path__)))
    for path, expected in PLAN["blobs"].items():
        _, package, relative = path.split("/", 2)
        data = (roots[package] / relative).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()
        require(actual == expected, f"upstream blob mismatch: {path}")
    inventory = json.loads((roots["hcsn_split_mesh"] / "CURRENT-MANIFEST.json").read_bytes())
    root = roots["hcsn_split_mesh"].parents[1]
    for path, digest in inventory["sources"].items():
        require(sha256((root / path).read_bytes()) == digest, f"split inventory mismatch: {path}")
    return {"extra_bound_blobs": len(PLAN["blobs"]), "split_inventory_files": len(inventory["sources"])}


def reflected(x, t, mu, sigma):
    x, t, mu, sigma = map(mp.mpf, (x, t, mu, sigma))
    scale = sigma * mp.sqrt(t)
    normal = lambda z: mp.erfc(-z / mp.sqrt(2)) / 2
    return normal((-x - mu * t) / scale) + mp.exp(-2 * mu * x / sigma**2) * normal((-x + mu * t) / scale)


def density_oracle(x, t, mu, sigma, dps):
    # v=A(1/s-1/t) scales the inverse-Gaussian integral relative to the deadline.
    # Each score below is the derivative at fixed integration time s before substitution.
    with mp.workdps(dps):
        x, t, mu, sigma = map(mp.mpf, (x, t, mu, sigma))
        a = x**2 / (2 * sigma**2)
        def integral(score):
            def integrand(v):
                s = a / (a / t + v)
                return mp.sqrt(s) * mp.exp(-v - mu**2 * s / (2 * sigma**2)) * score(s)
            return mp.quad(integrand, [0, 1, 4, 16, mp.inf])
        weight = integral(lambda s: 1)
        scale = x * mp.exp(-a / t - mu * x / sigma**2) / (sigma * mp.sqrt(2 * mp.pi) * a)
        mass = scale * weight
        density_t = x * mp.exp(-(x + mu * t)**2 / (2 * sigma**2 * t)) / (sigma * mp.sqrt(2 * mp.pi * t**3))
        log_gradient = (
            integral(lambda s: 1 / x - (x + mu * s) / (sigma**2 * s)) / weight,
            density_t / mass,
            integral(lambda s: -(x + mu * s) / sigma**2) / weight,
            integral(lambda s: -1 / sigma + (x + mu * s)**2 / (sigma**3 * s)) / weight,
        )
        return mass, log_gradient


def tensor(value, grad=False):
    return torch.tensor(value, dtype=torch.float64, requires_grad=grad)


def heads(x, time, mu, sigma, discount):
    values = tuple(tensor(v, True) for v in (x, time, mu, sigma))
    x, time, mu, sigma = values
    mass = TensorDiffusion(mu, sigma, tensor(discount)).hit_probability(x, time)
    log_mass = _first_hit_logprob(x, time, mu, sigma)
    mass_gradient = torch.autograd.grad(mass, values)
    log_gradient = torch.autograd.grad(log_mass, values)
    return {
        "probability": mass.item(), "log_probability": log_mass.item(),
        "gradient": [v.item() for v in mass_gradient], "log_gradient": [v.item() for v in log_gradient],
    }


def rel(value, reference):
    return float(abs(mp.mpf(value) / reference - 1))


def focal(x, t, mu, sigma, discount, boundary, reset):
    f, score = density_oracle(x, t, mu, sigma, PLAN["quadrature_dps"][1])
    coarse, coarse_score = density_oracle(x, t, mu, sigma, PLAN["quadrature_dps"][0])
    reflected_f = reflected(x, t, mu, sigma)
    reflected_score = mp.diff(lambda *v: mp.log(reflected(*v)), (x, t, mu, sigma), (1, 0, 0, 0))
    oracle_error = max(rel(coarse, f), rel(reflected_f, f), rel(reflected_score, score[0]),
                       *(rel(v, ref) for v, ref in zip(coarse_score, score, strict=True)))
    require(oracle_error <= GATE["independent_oracle_relative"], "independent integral/reference mismatch")
    computed = heads(x, t, mu, sigma, discount)
    err_mass = rel(computed["probability"], f)
    err_log = float(abs(computed["log_probability"] - mp.log(f)))
    err_gradient = max(rel(v, f * s) for v, s in zip(computed["gradient"], score, strict=True))
    err_log_gradient = max(rel(v, s) for v, s in zip(computed["log_gradient"], score, strict=True))
    require(err_mass <= GATE["focal_relative_value"] and err_log <= GATE["nodal_absolute_log"], "reset value mismatch")
    require(max(err_gradient, err_log_gradient) <= GATE["focal_relative_gradient"], "reset gradient mismatch")
    b, r = tensor(boundary, True), tensor(reset, True)
    margin = torch.log(r) - b
    require(margin.item() == x, "reset margin differs from frozen grid node")
    m = TensorDiffusion(tensor(mu), tensor(sigma), tensor(discount)).hit_probability(margin, t)
    db, dr = torch.autograd.grad(m, (b, r))
    require(max(rel(db.item(), -f * score[0]), rel(dr.item(), f * score[0] / reset)) <= GATE["focal_relative_gradient"], "physical coordinate chain mismatch")
    require(abs(db.item() + reset * dr.item()) <= abs(db.item()) * 2e-14, "boundary/reset gradient identity")
    return dict(time=t, independent_cdf=mp.nstr(f, 48), relative_oracle_disagreement=oracle_error,
                public_probability_relative_error=err_mass, absolute_log_error=err_log,
                probability_gradient_max_relative_error=err_gradient, log_gradient_max_relative_error=err_log_gradient,
                physical_gradient_boundary=db.item(), physical_gradient_reset=dr.item(), **computed)


def nodal(theta, focal_rows):
    rows = []
    dist = TensorDiffusion(tensor(theta[1]), tensor(theta[2]), tensor(theta[4]))
    for geometry in test_split.GEOMETRIES:
        model, _ = test_split.split_model(theta, **geometry)
        nodes = model.spatial.nodes
        require(nodes[32] == PLAN["x"] and len(nodes) == 65, "wrong frozen node geometry")
        for focal_row in focal_rows:
            t = focal_row["time"]
            points = tensor(nodes[1:])
            mass = dist.hit_probability(points, t).tolist()
            logs = _first_hit_logprob(points, tensor(t), dist.mu, dist.sigma).tolist()
            exact = [reflected(x, t, theta[1], theta[2]) for x in nodes[1:]]
            normal = [i for i, f in enumerate(exact) if f >= sys.float_info.min]
            relative_error = max(rel(mass[i], exact[i]) for i in normal)
            log_error = max(float(abs(v - mp.log(f))) for v, f in zip(logs, exact, strict=True))
            require(relative_error < GATE["normal_nodal_relative_value"] and log_error < GATE["nodal_absolute_log"], "nodal readout mismatch")
            raw = float(expm(t * model.spatial.matrix())[32, 0])
            factor = raw / float(focal_row["independent_cdf"])
            if t == .01:
                require(factor - 1 > 1e5, "original rare mesh failure must remain visible")
            upper_reach = reflected(geometry["endpoint"] - nodes[32], t, -theta[1], theta[2])
            rows.append(dict(geometry=geometry, time=t, positive_nodes=len(points), normal_probabilities=len(normal),
                             subnormal_nonzero=sum(0 < p < sys.float_info.min for p in mass), zeros=sum(p == 0 for p in mass),
                             max_normal_probability_relative_error=relative_error, max_log_absolute_error=log_error,
                             original_ctmc=raw, original_ctmc_over_continuum=factor, upper_reach_bound=mp.nstr(upper_reach, 15)))
    return rows


def limits(x, mu, sigma, discount):
    a = x**2 / (2 * sigma**2)
    short = []
    for t in (1e-3, 1e-4, 1e-5):
        row = heads(x, t, mu, sigma, discount)
        dx, dt, dmu, dsigma = row["log_gradient"]
        scaled = (t * row["log_probability"], t * t * dt, t * dx, dmu, t * dsigma)
        expected = (-a, a, -x / sigma**2, -x / sigma**2, x*x / sigma**3)
        short.append(dict(time=t, probability=row["probability"], log_probability=row["log_probability"],
                          scaled_log_derivatives=list(scaled[1:]), t_log_probability=scaled[0],
                          max_relative_limit_error=max(rel(val, ref) for val, ref in zip(scaled, expected, strict=True))))
    require(short[-1]["max_relative_limit_error"] < GATE["short_limit_relative_at_1e_5"], "short-time asymptotics mismatch")
    t = .01
    z = mu * math.sqrt(t) / sigma
    normal = .5 * math.erfc(-z / math.sqrt(2))
    boundary_dx = -2 * math.exp(-.5 * z**2) / (math.sqrt(2 * math.pi * t) * sigma) - 2 * mu * normal / sigma**2
    boundary = []
    for distance in (1e-3, 1e-4, 1e-5, 1e-6):
        row = heads(distance, t, mu, sigma, discount)
        boundary.append(dict(x=distance, probability=row["probability"], gradient_x=row["gradient"][0],
                             relative_gradient_limit_error=rel(row["gradient"][0], boundary_dx)))
    require(boundary[-1]["relative_gradient_limit_error"] < GATE["near_boundary_gradient_relative_at_1e_6"], "boundary gradient limit")
    require(0 < 1 - boundary[-1]["probability"] < GATE["near_boundary_probability_gap_at_1e_6"], "boundary probability limit")
    dist = TensorDiffusion(tensor(mu), tensor(sigma), tensor(discount))
    atoms = [dist.hit_probability(tensor(d), h).item() for d, h in ((0., t), (x, 0.), (0., 0.))]
    require(atoms == [1., 0., 1.], "atom forward values")
    try:
        dist.hit_probability(tensor(0., True), t)
    except ValueError as exc:
        require("atoms" in str(exc), "unexpected atom exception")
    else:
        raise RuntimeError("origin autodiff should be unqualified")
    return dict(short=short, boundary=boundary, boundary_limit_gradient=boundary_dx, atom_values=atoms)


def evidence():
    mp.mp.dps = 110
    source = verify_source()
    fixture = test_split.SplitMesh()
    fixture.setUp()
    theta = fixture.theta.copy()
    theta[2] = PLAN["sigma"]  # The original rare-first-passage case overrides the .08 generator case.
    b, mu, sigma, reset, discount = map(float, theta)
    require((b, mu, sigma, discount) == (PLAN["B"], PLAN["mu"], PLAN["sigma"], PLAN["discount"]), "frozen parameters")
    require(reset == math.exp(.51), "wrong frozen absolute reset")
    x = math.log(reset) - b
    require(x == PLAN["x"], "incorrect margin")
    rows = [focal(x, t, mu, sigma, discount, b, reset) for t in PLAN["times"]]
    result = dict(scope=PLAN["scope"], upstream=PLAN["source"], source=source, protocol_sha256=sha256(PROTOCOL.read_bytes()),
                  verifier_sha256=sha256(Path(__file__).read_bytes()), parameters=theta.tolist(),
                  gradient_order=["distance", "deadline", "mu", "sigma"], focal=rows, nodal=nodal(theta, rows),
                  limits=limits(x, mu, sigma, discount), runtime=dict(python=platform.python_version(), torch=torch.__version__,
                  numpy=np.__version__, scipy=scipy.__version__, mpmath=mp.__version__))
    require(verify_source() == source, "upstream source drift during evaluation")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    destination = parser.parse_args().output
    encoded = json.dumps(evidence(), allow_nan=False, indent=2) + "\n"
    if destination:
        destination.write_text(encoded)
    else:
        print(encoded, end="")
