"""Independent numerical checks for the new Brownian, not OU, contract."""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from scipy.integrate import quad
from scipy.special import log_ndtr, ndtr
import torch

from .kernels import (KERNEL_VERSION, BrownianEventDynamics, brownian_first_exit,
                      brownian_killed_bins, gaussian_events, gaussian_propagate,
                      normal_cdf, probit_events, recovery_probability)


def spectral_density(y, x, drift, sigma, dt, boundary):
    """Independent sine-eigenfunction killed density; moderate regimes only."""
    width = 2 * boundary
    wave = np.arange(1, 401) * np.pi / width
    series = np.sin(wave * (x + boundary)) * np.sin(wave * (y + boundary))
    series *= np.exp(-0.5 * sigma**2 * wave**2 * dt)
    tilt = np.exp(drift * (y - x) / sigma**2 - drift**2 * dt / (2 * sigma**2))
    return float(2 / width * tilt * series.sum())


def spectral_exit(x, drift, sigma, dt, boundary):
    """Integrate spectral boundary flux from dt to infinity, then subtract."""
    width, start = 2 * boundary, x + boundary
    n = np.arange(1, 401)
    wave = n * np.pi / width
    decay = 0.5 * sigma**2 * wave**2 + drift**2 / (2 * sigma**2)
    tail = np.sin(wave * start) * wave * np.exp(-decay * dt) / decay
    upper_eventual = (start / width if abs(drift) < 1e-12 else
                      -np.expm1(-2 * drift * start / sigma**2) / -np.expm1(-2 * drift * width / sigma**2))
    upper = upper_eventual - sigma**2 / width * np.exp(drift * (width - start) / sigma**2) * ((-1.)**(n + 1) * tail).sum()
    lower = 1 - upper_eventual - sigma**2 / width * np.exp(-drift * start / sigma**2) * tail.sum()
    return np.array([upper, lower])


def tensor(x):
    return torch.tensor(x, dtype=torch.float64)


def analytic_checks():
    cases = []
    maximum_bins = maximum_flux = maximum_mass = 0.0
    for x, drift, sigma, dt, boundary in ((0., 1., .45, 1., 1.),
                                        (.2, -.4, .6, .7, 1.),
                                        (-.3, .2, .7, .9, .8)):
        edges = np.linspace(-boundary, boundary, 10)
        bins = brownian_killed_bins(tensor(x), tensor(edges), tensor(drift), tensor(sigma), dt, tensor(boundary)).numpy()
        reference = np.array([quad(spectral_density, a, b, args=(x, drift, sigma, dt, boundary),
                                   epsabs=2e-13, epsrel=2e-12)[0] for a, b in zip(edges[:-1], edges[1:])])
        events = brownian_first_exit(tensor(x), tensor(drift), tensor(sigma), dt, tensor(boundary)).numpy()
        flux = spectral_exit(x, drift, sigma, dt, boundary)
        bin_error = float(np.max(np.abs(bins - reference)))
        flux_error = float(np.max(np.abs(events - flux)))
        mass_error = abs(float(bins.sum() + events.sum()) - 1)
        maximum_bins, maximum_flux, maximum_mass = max(maximum_bins, bin_error), max(maximum_flux, flux_error), max(maximum_mass, mass_error)
        cases.append({"parameters": [x, drift, sigma, dt, boundary], "bin_probabilities": bins.tolist(),
                      "independent_quadrature": reference.tolist(), "events_plus_minus": events.tolist(),
                      "independent_flux": flux.tolist(), "max_bin_error": bin_error,
                      "max_flux_error": flux_error, "mass_error": mass_error})
    sigma, drift, dt = .05, 1., .8
    reference = ndtr((drift * dt - 1) / (sigma * math.sqrt(dt))) + np.exp(2 * drift / sigma**2 + log_ndtr((-drift * dt - 1) / (sigma * math.sqrt(dt))))
    actual = float(brownian_first_exit(tensor(0.), tensor(drift), tensor(sigma), dt, tensor(1.))[0])
    z = tensor([-8., -9., -10., -20., -30.])
    stable = normal_cdf(z).numpy()
    expected = ndtr(z.numpy())
    mean = tensor([-2., -.1, .3, 1., 5.])
    variance = tensor([.3, .5, .2, 1., .7])
    analytic = gaussian_events(mean, variance, -.4, .6)
    probit = probit_events(mean, variance, -.4, .6)
    binary = gaussian_events(mean, variance, .2, .2)
    m, v = gaussian_propagate(tensor(0.), tensor(0.), 1.5, .45, 10.)
    return {"independent_cases": cases, "maximum_bin_error": maximum_bins, "maximum_flux_error": maximum_flux,
            "maximum_mass_error": maximum_mass,
            "low_noise": {"actual": actual, "single_upper_reference": float(reference),
                          "competing_lower_bound_log": -800., "absolute_error": abs(actual - reference)},
            "tails": {"z": z.tolist(), "stable": stable.tolist(), "scipy": expected.tolist(),
                      "maximum_relative_error": float(np.max(np.abs(stable / expected - 1)))},
            "gaussian_probit_maximum_difference": float((analytic - probit).abs().max()),
            "same_strike_complement_error": float((binary.sum(-1) - 1).abs().max()),
            "unbounded_example": {"mean": float(m), "variance": float(v), "has_spatial_projection": False}}


def absorbing_matrix(grid, dt, drive=.6, sigma=.45):
    x = torch.linspace(-1., 1., grid + 2, dtype=torch.float64)[1:-1]
    edges = torch.cat((tensor([-1.]), (x[:-1] + x[1:]) / 2, tensor([1.])))
    active = brownian_killed_bins(x, edges, tensor(drive), tensor(sigma), dt, tensor(1.))
    events = brownian_first_exit(x, tensor(drive), tensor(sigma), dt, tensor(1.))
    rows = torch.cat((active, events), -1)
    return torch.cat((rows, torch.cat((torch.zeros(2, grid, dtype=torch.float64), torch.eye(2, dtype=torch.float64)), -1)), 0)


def refinement_checks():
    reference = brownian_first_exit(tensor(0.), tensor(.6), tensor(.45), 1., tensor(1.)).numpy()
    rows = []
    for grid, parts in ((15, 4), (31, 4), (63, 4), (127, 4),
                        (15, 2), (31, 4), (63, 8), (127, 16),
                        (31, 1), (31, 2), (31, 8), (31, 16)):
        transition = absorbing_matrix(grid, 1. / parts)
        final = torch.linalg.matrix_power(transition, parts)[grid // 2]
        rows.append({"grid": grid, "subintervals": parts, "events": final[-2:].tolist(),
                     "maximum_event_error": float(np.max(np.abs(final[-2:].numpy() - reference))),
                     "mass_error": abs(float(final.sum()) - 1)})
    q_ref = tensor(.65)
    rate = -torch.log1p(-q_ref)
    recovery = []
    for dt in (1., .1, .01):
        q = recovery_probability(rate, dt)
        cohort = float((1 - q) ** round(1 / dt))
        recovery.append({"dt": dt, "q": float(q), "unreleased_after_physical_time_one": cohort,
                         "cohort_error": abs(cohort - .35), "mean_rounded_release_delay": dt / float(q)})
    order = []
    for sigma, boundary, drive in ((.8, .35, 1.5), (.45, 1., -.7), (.05, 1., 1.)):
        x = tensor(np.linspace(-boundary, boundary, 9)[1:-1])
        values = [brownian_first_exit(x, tensor(drive), tensor(sigma), 1., tensor(boundary), image_terms=n).numpy() for n in (4, 8, 12, 16)]
        order.append({"sigma": sigma, "boundary": boundary, "drive": drive,
                      "orders": [4, 8, 12, 16], "max_difference_from_order_16": [float(np.max(np.abs(v - values[-1]))) for v in values]})
    return {"projected_successor_refinement": rows, "exact_unprojected_event_reference": reference.tolist(),
            "physical_recovery": recovery, "image_order": order,
            "scope": "Absorbing subinterval diagnostic excludes reset/recovery; dt-only changes can worsen repeated projection. Recovery release remains rounded to the next tick and events freeze until tick end."}


def branch_value(matrices, grid, readout):
    """Backward expectation of a nonlinear loss with event count in state."""
    horizon, states = len(matrices), grid + 2
    counts = torch.arange(horizon + 1)
    float_counts = counts.to(torch.float64)
    state_score = torch.arange(states, dtype=torch.float64) / (states - 1) - .5
    value = torch.sin(readout * state_score[:, None] + .3 * float_counts) + .2 * float_counts.square()
    emitted = (torch.arange(states)[:, None] < grid) & (torch.arange(states)[None, :] >= grid)
    targets = torch.clamp(counts[None, None, :] + emitted[:, :, None], max=horizon)
    destinations = torch.arange(states)[None, :, None].expand(states, states, horizon + 1)
    for transition in reversed(matrices):
        value = (transition[:, :, None] * value[destinations, targets]).sum(1)
    return value[grid // 2, 0]


def enumerate_value(matrices, grid, readout):
    """Independent complete state-path sum; never evaluates averaged features."""
    states = grid + 2
    result = expected_count = expected_state_score = 0.
    for path in itertools.product(range(states), repeat=len(matrices)):
        previous, probability, count = grid // 2, 1., 0
        for transition, successor in zip(matrices, path):
            probability *= transition[previous, successor]
            count += int(previous < grid and successor >= grid)
            previous = successor
        score = previous / (states - 1) - .5
        result += probability * (np.sin(readout * score + .3 * count) + .2 * count**2)
        expected_count += probability * count
        expected_state_score += probability * score
    mean_loss = np.sin(readout * expected_state_score + .3 * expected_count) + .2 * expected_count**2
    return float(result), float(expected_count), float(mean_loss)


def gradient_checks():
    output = []
    for mode in BrownianEventDynamics.MODES:
        cell = BrownianEventDynamics(mode, 5)
        drive = tensor(.35).requires_grad_()
        readout = tensor(.9).requires_grad_()

        def matrices():
            return [cell.transition_matrix(drive + offset, dt)[0][0]
                    for offset, dt in ((0., .6), (.15, .8), (-.1, .5))]

        actual = matrices()
        value = branch_value(actual, cell.n_grid, readout)
        names, parameters = zip(*[(name, p) for name, p in cell.named_parameters() if p.requires_grad])
        names, parameters = list(names) + ["content_drive", "readout"], list(parameters) + [drive, readout]
        derivatives = torch.autograd.grad(value, parameters, allow_unused=True)
        independent, count, mean_loss = enumerate_value([p.detach().numpy() for p in actual], 5, float(readout.detach()))
        gradients = []
        for name, parameter, derivative in zip(names, parameters, derivatives):
            old, step = float(parameter.detach()), 2e-5
            values = []
            for sign in (1, -1):
                with torch.no_grad():
                    parameter.fill_(old + sign * step)
                    values.append(enumerate_value([p.numpy() for p in matrices()], 5, float(readout))[0])
            with torch.no_grad():
                parameter.fill_(old)
            finite = (values[0] - values[1]) / (2 * step)
            automatic = 0. if derivative is None else float(derivative)
            gradients.append({"parameter": name, "automatic": automatic, "independent_branch_finite_difference": finite,
                              "absolute_error": abs(automatic - finite)})
        output.append({"mode": mode, "horizon": 3, "complete_leaf_paths": 7**3,
                       "expected_nonlinear_loss": float(value.detach()), "independent_enumeration": independent,
                       "enumeration_error": abs(float(value.detach()) - independent), "expected_event_count": count,
                       "loss_of_mean_features": mean_loss, "jensen_difference": independent - mean_loss,
                       "gradients": gradients, "maximum_gradient_error": max(g["absolute_error"] for g in gradients)})
    return output


def run_audit():
    torch.set_num_threads(1)
    started = time.perf_counter()
    analytic, refinement, gradients = analytic_checks(), refinement_checks(), gradient_checks()
    gates = {
        "independent_killed_bins": analytic["maximum_bin_error"] <= 2e-11,
        "independent_boundary_flux": analytic["maximum_flux_error"] <= 2e-11,
        "low_noise_corner": analytic["low_noise"]["absolute_error"] <= 1e-12,
        "extreme_gaussian_tails": analytic["tails"]["maximum_relative_error"] <= 2e-12,
        "gaussian_probit_identity": analytic["gaussian_probit_maximum_difference"] == 0.,
        "same_strike_complement": analytic["same_strike_complement_error"] <= 2e-15,
        "complete_branch_expectation": max(g["enumeration_error"] for g in gradients) <= 2e-12,
        "complete_branch_gradients": max(g["maximum_gradient_error"] for g in gradients) <= 2e-7,
        "recovery_original_cohort": max(r["cohort_error"] for r in refinement["physical_recovery"]) <= 2e-13,
    }
    return {"created_utc": datetime.now(timezone.utc).isoformat(), "kernel_version": KERNEL_VERSION,
            "runtime": {"python": platform.python_version(), "torch": torch.__version__, "numpy": np.__version__, "scipy": scipy.__version__, "torch_threads": torch.get_num_threads()},
            "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ("kernels.py", "kernel_audit.py")},
            "analytic": analytic, "refinement": refinement, "complete_successor_gradients": gradients,
            "gates": {name: "PASS" if passed else "FAIL" for name, passed in gates.items()},
            "wall_seconds": time.perf_counter() - started,
            "scope": "New constant-drift Brownian kernel only. This does not certify R7 OU, arbitrary image-series regimes, continuous-time regeneration, or a task advantage. Tests compare the expected nonlinear path loss, not a loss on mean features."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"gates": result["gates"], "wall_seconds": result["wall_seconds"]}))


if __name__ == "__main__":
    main()
