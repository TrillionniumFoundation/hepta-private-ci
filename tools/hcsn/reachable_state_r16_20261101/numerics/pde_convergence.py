"""Deterministic convergence checks for a stated fixed-boundary PDE profile.

This is not a continuum proof for the HX/regenerative/controlled model.  It
checks the shared half-cell absorbing-face stencil against a separately
derived spectral solution of u_t = D u_xx, u(0)=0, u_x(L)=0.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.linalg import eigh_tridiagonal, solve_banded


def spectral_bins(edges, x0, duration, diffusion, terms=1024):
    """Integrate the sine-series transition density exactly within each bin."""
    length = float(edges[-1])
    wave = (np.arange(terms) + .5) * np.pi / length
    decay = np.exp(-diffusion * wave ** 2 * duration)
    coefficient = 2 / length * np.sin(wave * x0) * decay / wave
    mass = coefficient @ (
        np.cos(wave[:, None] * edges[:-1])
        - np.cos(wave[:, None] * edges[1:]))
    survival = float(np.sum(coefficient))  # cos(k L)=0.
    next_wave = (terms + .5) * np.pi / length
    # A geometric envelope bounds the absolute uniform-in-bin residual.
    # Preserve a positive bound at floating underflow, never assert zero tail.
    log_tail = (np.log(4 / (length * next_wave))
                - diffusion * next_wave ** 2 * duration
                - np.log(-np.expm1(-diffusion * (np.pi / length) ** 2
                                  * (2 * terms + 2) * duration)))
    tail = max(float(np.nextafter(0., 1.)), float(np.exp(log_tail)))
    return mass, survival, tail


def finite_volume(cells, length, diffusion, x0):
    spacing = length / cells
    rate = diffusion / spacing ** 2
    diagonal = np.full(cells, -2 * rate)
    diagonal[0], diagonal[-1] = -3 * rate, -rate
    off_diagonal = np.full(cells - 1, rate)
    centers = (np.arange(cells) + .5) * spacing
    lower = int(np.searchsorted(centers, x0) - 1)
    if not 0 <= lower < cells - 1:
        raise ValueError("Initial point must lie between interior centers")
    fraction = (x0 - centers[lower]) / spacing
    initial = np.zeros(cells)
    initial[lower:lower + 2] = 1 - fraction, fraction
    return diagonal, off_diagonal, initial


def semigroup(diagonal, off_diagonal, initial, duration):
    eigenvalues, eigenvectors = eigh_tridiagonal(diagonal, off_diagonal)
    return eigenvectors @ (np.exp(eigenvalues * duration)
                           * (eigenvectors.T @ initial))


def implicit_euler(diagonal, off_diagonal, initial, duration, steps):
    dt = duration / steps
    band = np.zeros((3, len(initial)))
    band[1] = 1 - dt * diagonal
    band[0, 1:] = -dt * off_diagonal
    band[2, :-1] = -dt * off_diagonal
    state = initial.copy()
    for _ in range(steps):
        state = solve_banded((1, 1), band, state)
    return state


def run():
    started = time.process_time()
    length, diffusion, x0 = .8, .045, .3
    durations = [.15, .45, 1.05, 2.10]
    spatial = []
    for cells in [16, 32, 64, 128, 256]:
        diagonal, off_diagonal, initial = finite_volume(
            cells, length, diffusion, x0)
        edges = np.linspace(0, length, cells + 1)
        for duration in durations:
            reference, survival, tail = spectral_bins(
                edges, x0, duration, diffusion)
            doubled, survival2, _ = spectral_bins(
                edges, x0, duration, diffusion, terms=2048)
            actual = semigroup(diagonal, off_diagonal, initial, duration)
            # The cemetery state is 1-sum(active), so this norm counts both
            # the unabsorbed distribution and total first-hit probability.
            first_hit_error = abs(float(actual.sum()) - survival)
            spatial.append(dict(cells=cells, duration=duration,
                active_l1=float(np.sum(np.abs(actual - reference))),
                probability_l1=float(np.sum(np.abs(actual - reference)))
                    + first_hit_error,
                first_hit_absolute_error=first_hit_error,
                exact_first_hit=1 - survival,
                numerical_first_hit=1 - float(actual.sum()),
                smallest_active_mass=float(actual.min()),
                exact_series_tail_bound=tail,
                doubled_series_difference=max(float(np.max(np.abs(reference - doubled))),
                                               abs(survival2 - survival))))
    temporal = []
    diagonal, off_diagonal, initial = finite_volume(128, length, diffusion, x0)
    duration = 1.05
    reference = semigroup(diagonal, off_diagonal, initial, duration)
    for steps in [16, 32, 64, 128, 256, 512]:
        actual = implicit_euler(diagonal, off_diagonal, initial, duration, steps)
        temporal.append(dict(steps=steps, dt=duration / steps,
            probability_l1=float(np.sum(np.abs(actual - reference)))
                + abs(float(actual.sum() - reference.sum())),
            minimum=float(actual.min()), survival=float(actual.sum())))
    spatial_orders = []
    for duration in durations:
        rows = [r for r in spatial if r["duration"] == duration]
        spatial_orders.extend(dict(duration=duration,
            coarse=a["cells"], fine=b["cells"],
            order=float(np.log2(a["probability_l1"] / b["probability_l1"])))
            for a, b in zip(rows, rows[1:]))
    temporal_orders = [float(np.log2(a["probability_l1"] / b["probability_l1"]))
                       for a, b in zip(temporal, temporal[1:])]
    gates = dict(
        nonnegative_with_float_roundoff=all(r["smallest_active_mass"] >= -1e-13
                                           for r in spatial),
        spatial_last_two_orders_at_least_1p8=all(
            r["order"] >= 1.8 for r in spatial_orders if r["coarse"] >= 64),
        temporal_last_two_orders_between_0p9_and_1p1=all(
            .9 <= order <= 1.1 for order in temporal_orders[-2:]),
        finest_l1_below_2e_minus_4=all(r["probability_l1"] < 2e-4
                                      for r in spatial if r["cells"] == 256),
        independent_series_stability=all(r["doubled_series_difference"] < 1e-13
                                         for r in spatial))
    return dict(schema="hcsn-r16-fixed-boundary-pde-v1", passed=all(gates.values()),
        scope="Constant diffusion, zero drift, fixed absorbing lower and reflecting upper faces; no recovery, moving boundary, control or full HX PDE.",
        parameters=dict(length=length, diffusion=diffusion, initial_point=x0),
        spatial=spatial, spatial_orders=spatial_orders,
        temporal=temporal, temporal_orders=temporal_orders, gates=gates,
        cpu_seconds=time.process_time() - started,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = run()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True,
                                          allow_nan=False) + "\n")
    print(json.dumps(dict(passed=result["passed"], gates=result["gates"],
                         cpu_seconds=result["cpu_seconds"]), sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
