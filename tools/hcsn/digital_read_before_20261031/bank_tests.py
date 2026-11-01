"""Bounded mathematical audit, independent SciPy spectral/Gaussian references.

Run with ``python -m tools.hcsn.digital_read_before_20261031.bank_tests``.
This does not train models or establish a continuous-network equivalence claim.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import ndtr
import torch

from .bank import FiniteCell, HORIZONS, THRESHOLDS, VERSION, gaussian_events, normal_interval


def _np(value):
    return value.detach().cpu().numpy()


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def spectral_reference(x, drift, sigma, dt, boundary, edges, terms=192, order=32):
    """Independent Dirichlet sine expansion and Gauss-Legendre integration.

    The competing exit probabilities use harmonic eventual-exit probabilities
    minus their killed-semigroup expectations. No Brownian image terms are used.
    This reference is used only in the explicitly recorded moderate-drift domain.
    """
    length, start = 2 * boundary, x + boundary
    nodes, weights = np.polynomial.legendre.leggauss(order)
    lo, hi = edges[:-1, None] + boundary, edges[1:, None] + boundary
    y = (lo + hi) / 2 + (hi - lo) / 2 * nodes
    w = (hi - lo) / 2 * weights
    n = np.arange(1, terms + 1, dtype=float)
    frequencies = n * math.pi / length
    coefficients = np.sin(frequencies * start) * np.exp(-0.5 * sigma**2 * frequencies**2 * dt)
    density = 2 / length * np.sum(np.sin(y[..., None] * frequencies) * coefficients, axis=-1)
    density *= np.exp(drift * (y - start) / sigma**2 - drift**2 * dt / (2 * sigma**2))
    bins = np.sum(w * density, axis=-1)

    def upper_harmonic(v):
        if abs(drift) < 1e-10:
            return v / length
        return np.expm1(-2 * drift * v / sigma**2) / np.expm1(-2 * drift * length / sigma**2)

    upper = upper_harmonic(start) - np.sum(w * density * upper_harmonic(y))
    lower = 1 - upper_harmonic(start) - np.sum(w * density * (1 - upper_harmonic(y)))
    return bins, np.array([lower, upper])


def gaussian_check():
    examples = [(-4., .3, -.8, .4), (.2, .7, -.6, .9), (4., .3, -.8, .4), (0., 1., 0., 0.)]
    errors = []
    for mean, var, lower, upper in examples:
        actual = _np(gaussian_events(mean, var, lower, upper))
        a, b = (lower - mean) / math.sqrt(var), (upper - mean) / math.sqrt(var)
        interval = ndtr(-a)-ndtr(-b) if a >= 0 else ndtr(b)-ndtr(a)
        expected = np.array([ndtr(a), interval, ndtr(-b)])
        errors.append(float(np.max(np.abs(actual-expected))))
    atom = _np(gaussian_events(torch.tensor([-1., 0., 1.], dtype=torch.float64), 0., 0., 0.))
    _require(np.array_equal(atom, [[1, 0, 0], [1, 0, 0], [0, 0, 1]]), "zero-variance tie convention")
    tails = []
    for lo, hi in [(-35., -34.99), (-12., -11.9), (8., 8.1), (12., 12.1), (30., 30.01)]:
        actual = float(normal_interval(torch.tensor(lo, dtype=torch.float64), torch.tensor(hi, dtype=torch.float64)))
        expected = ndtr(-lo)-ndtr(-hi) if lo >= 0 else ndtr(hi)-ndtr(lo)
        relative = abs(actual-expected)/expected
        tails.append(dict(lower=lo, upper=hi, probability=actual, scipy_probability=float(expected), relative_error=relative))
        _require(actual > 0 and relative < 2e-10, "Gaussian tail cancellation")
    _require(max(errors) < 2e-14, "Gaussian endpoint/probit disagreement")
    cell = FiniteCell("clocked", raw=[.1, -.2, .3, -.1, .2, -.3, .4])
    p = {k: float(v.detach()) for k, v in cell.physical().items()}
    symbol, reliability = -1, .85
    drift = p["drift_bias"]+p["gain"]*symbol*(2*reliability-1)
    x = _np(cell.centers_normalized)*p["boundary"]
    reference = np.column_stack([ndtr((x+drift*h-k*p["boundary"])/(p["diffusion"]*math.sqrt(h)))
                                 for h in HORIZONS for k in THRESHOLDS])
    bank_error = float(np.max(np.abs(_np(cell.features(symbol, reliability))[:15, :9]-reference)))
    _require(bank_error < 2e-14, "bank/probit numerical identity")
    _require(np.array_equal(_np(cell.features(0, .5))[-2:, :10], np.zeros((2, 10))), "refractory is not an active forecast")
    return dict(endpoint_max_abs_error=max(errors), bank_probit_max_abs_error=bank_error,
                tails=tails, atom_convention="put <= strike; call > strike; equal strike idle=0")


def spectral_check():
    cases, errors = [], []
    for raw in ([0.]*7, [.7, .4, -.6, .5, .6, -.3, .2]):
        cell = FiniteCell("first_passage", raw=raw)
        p = {k: float(v.detach()) for k, v in cell.physical().items()}
        edges = _np(cell.edges_normalized)*p["boundary"]
        centers = _np(cell.centers_normalized)*p["boundary"]
        for dt, symbol, reliability in [(0.25, 1, .85), (.75, -1, .85), (1.5, 0, .5)]:
            drift = p["drift_bias"]+p["gain"]*symbol*(2*reliability-1)
            t, _ = cell.transition(dt, symbol, reliability)
            t = _np(t)
            maximum = 0.
            for row in (0, 3, 7, 11, 14):
                bins, exit_mass = spectral_reference(centers[row], drift, p["diffusion"], dt, p["boundary"], edges)
                maximum = max(maximum, float(np.max(np.abs(t[row]-np.r_[bins, exit_mass]))))
            errors.append(maximum)
            cases.append(dict(raw=list(raw), dt=dt, symbol=symbol, reliability=reliability,
                              drift=drift, physical=p, maximum_absolute_error=maximum))
    _require(max(errors) < 3e-10, "Brownian image law disagrees with independent sine law")
    return dict(reference="192-term Dirichlet sine law, 32-point Gauss-Legendre per bin, harmonic exit identity",
                cases=cases, maximum_absolute_error=max(errors),
                limitation="numerical independent reference on listed moderate-drift points, not interval certification")


def envelope_check():
    maximum_mass_error, minimum_entry, maximum_order_error, calls = 0., 1., 0., 0
    raw_cases = [[0.]*7, [6.]*7, [-6.]*7, [6., -6., 6., 6., -6., 6., -6.], [-6., 6., 6., -6., 6., -6., 6.]]
    for mode in ("ordinary", "clocked", "first_passage"):
        for raw in raw_cases:
            cell = FiniteCell(mode, raw=raw)
            for dt in (0., .25, 1., 2.):
                for symbol, reliability in [(-1, 1.), (0, .5), (1, 1.)]:
                    transition, event = cell.transition(dt, symbol, reliability)
                    t, e = _np(transition), _np(event)
                    maximum_mass_error = max(maximum_mass_error, float(np.max(np.abs(t.sum(-1)-1))))
                    minimum_entry = min(minimum_entry, float(t.min()))
                    _require(np.allclose(e[:15], t[:15, -2:].sum(-1), rtol=0, atol=2e-15), "fresh event counting")
                    _require(np.array_equal(e[-2:], [0., 0.]), "old refractory releases are not events")
                    if mode == "ordinary":
                        _require(np.count_nonzero(e) == 0, "ordinary must have no internal event")
                    if mode == "first_passage" and dt:
                        other = FiniteCell(mode, raw=raw, image_terms=16)
                        maximum_order_error = max(maximum_order_error, float(np.max(np.abs(t-_np(other.transition(dt, symbol, reliability)[0])))))
                    calls += 1
    _require(maximum_mass_error <= 2e-10 and minimum_entry >= 0, "finite mass envelope")
    _require(maximum_order_error < 2e-11, "image-order truncation discrepancy")
    return dict(transition_calls=calls, raw_cases=raw_cases, durations=[0., .25, 1., 2.],
                max_row_mass_error=maximum_mass_error, minimum_entry=minimum_entry,
                image_terms_12_vs_16_max_abs_error=maximum_order_error,
                limitation="finite sample of bounded parameter envelope; not a proof for every raw value")


def gradient_check():
    results = []
    rng = np.random.default_rng(930731)
    matrix_weights = torch.tensor(rng.normal(size=(17, 17)), dtype=torch.float64)
    feature_weights = torch.tensor(rng.normal(size=(17, 12)), dtype=torch.float64)
    for mode in ("ordinary", "clocked", "first_passage"):
        raw = torch.tensor([.3, -.4, .5, -.2, .25, -.3, .1], dtype=torch.float64)
        cell = FiniteCell(mode, raw=raw)

        def objective():
            t, e = cell.transition(.75, -1, .85)
            return (t*matrix_weights).sum() + .2*(cell.features(-1, .85)*feature_weights).sum() + .17*e.sum()

        auto = _np(torch.autograd.grad(objective(), cell.raw)[0])
        finite = np.zeros(7)
        epsilon = 1e-5
        for i in range(7):
            with torch.no_grad():
                cell.raw.copy_(raw)
                cell.raw[i] += epsilon
            plus = float(objective().detach())
            with torch.no_grad():
                cell.raw.copy_(raw)
                cell.raw[i] -= epsilon
            minus = float(objective().detach())
            finite[i] = (plus-minus)/(2*epsilon)
        with torch.no_grad():
            cell.raw.copy_(raw)
        error = float(np.max(np.abs(auto-finite)))
        _require(np.isfinite(auto).all() and error < 3e-7, "local raw-parameter gradient")
        if mode == "ordinary":
            _require(np.array_equal(auto[4:], np.zeros(3)), "ordinary inactive parameter gradients")
        results.append(dict(mode=mode, raw=raw.tolist(), autograd=auto.tolist(), finite_difference=finite.tolist(),
                            epsilon=epsilon, maximum_absolute_error=error))
    return results


def projection_diagnostic():
    """Two killed half-steps against a whole-interval first-exit probability."""
    raw, symbol, reliability = [0.]*7, 1, .7
    rows = []
    for n in (15, 31, 63):
        cell = FiniteCell("first_passage", raw=raw, n_grid=n)
        full, _ = cell.transition(1., symbol, reliability)
        half, _ = cell.transition(.5, symbol, reliability)
        p0 = cell.initial()[:n]
        projected_hit = float(1-(p0 @ half[:n, :n] @ half[:n, :n]).sum().detach())
        single_hit = float(full[n//2, -2:].sum().detach())
        rows.append(dict(active_bins=n, one_interval_first_hit=single_hit,
                         two_projected_killed_intervals_first_hit=projected_hit,
                         absolute_projection_difference=abs(single_hit-projected_hit)))
    return dict(results=rows, interpretation="Diagnostic of repeated voltage projection only; no reset or release in the killed comparison. No continuous-equivalence admission.")


def run():
    torch.set_num_threads(1)
    start, cpu = time.perf_counter(), time.process_time()
    result = dict(schema="digital.bank.mathematical.audit.v1", kernel_version=VERSION,
                  torch_version=torch.__version__, dtype="float64",
                  scope="Mathematical Gaussian/Brownian probability and finite-kernel audit only. Free-endpoint bank features are not calibrated probabilities of FullHX observations, hidden labels, task success, or future action value.",
                  gaussian=gaussian_check(), spectral=spectral_check(), envelope=envelope_check(),
                  local_gradients=gradient_check(), projection=projection_diagnostic())
    cell = FiniteCell("clocked")
    artifact = cell.export([dict(dt=.5, symbol=0, reliability=.5), dict(dt=1., symbol=1, reliability=.85)])
    _require(len(artifact["contexts"]) == 2 and len(artifact["feature_names"]) == 12, "export shape")
    result["export_roundtrip"] = json.loads(json.dumps(artifact, allow_nan=False)) == artifact
    result["source_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (Path(__file__), Path(__file__).with_name("bank.py"))}
    result.update(passed=True, wall_seconds=time.perf_counter()-start, cpu_seconds=time.process_time()-cpu)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = run()
    serialized = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized+"\n")
    print(serialized)


if __name__ == "__main__":
    main()
