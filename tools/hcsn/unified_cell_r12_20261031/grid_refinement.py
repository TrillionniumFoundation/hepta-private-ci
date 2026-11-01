"""Independent sparse finite-grid refinement of the R12 joint process.

This diagnostic reconstructs the declared centered generator directly from its
rates. A 512-cell solution is a *fine finite reference*, not a continuum oracle
or a bound on grid/domain/Erlang error. The 256/512 discrepancy stays visible.
The two-stage Erlang law and reflecting upper endpoint are deliberately held
fixed, so this study does not validate deterministic refractory delay or an
unbounded diffusion. No content classification outcomes are read here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
from scipy.sparse import block_diag, coo_matrix, csc_matrix, bmat
from scipy.sparse.linalg import expm_multiply

from .cell import BASE_THETA, Cell, DEFAULT_THETA, PROTOCOL
from ..calibrated_operator_r11_20261031.numerics.kernel import evaluate


def independent_generator(cells, financial_theta):
    """Sparse row generator including the bit, built without Cell.Q."""
    sigma = financial_theta[2]
    drift = financial_theta[0] - financial_theta[1] - sigma * sigma / 2
    h = float(PROTOCOL["log_upper"]) / cells
    centers = (np.arange(cells) + .5) * h
    boundary = float(evaluate(financial_theta, .4, coordinate="log_distance")[0][0])
    reset = np.log(float(PROTOCOL["reset_asset"]) / boundary)
    if not centers[0] < reset < centers[-1]:
        raise ValueError("Reference reset falls outside represented centers")
    lower = int(np.searchsorted(centers, reset) - 1)
    f = (reset - centers[lower]) / h
    weights = [(lower, 1 - f), (lower + 1, f)]
    d = sigma * sigma / 2
    up, down, absorption = d / h ** 2 + drift / (2 * h), d / h ** 2 - drift / (2 * h), 2 * d / h ** 2
    if min(up, down, absorption) <= 0:
        raise ValueError("Reference centered rates must be positive")
    phases = int(PROTOCOL["recovery_phases"])
    size = 2 * (cells + phases)
    rows, columns, values = [], [], []
    events = np.zeros(size)

    def edge(source, destination, rate):
        rows.extend((source, source))
        columns.extend((destination, source))
        values.extend((rate, -rate))

    for phase in range(cells):
        for bit in (0, 1):
            source = 2 * phase + bit
            if phase + 1 < cells:
                edge(source, source + 2, up)
            if phase:
                edge(source, source - 2, down)
            else:
                edge(source, 2 * cells + bit, absorption)
                events[source] = absorption
    recovery_rate = phases / float(PROTOCOL["recovery_mean"])
    retention = (1 + float(PROTOCOL["content_retention"])) / 2
    for bit in (0, 1):
        for phase in range(cells, cells + phases - 1):
            edge(2 * phase + bit, 2 * (phase + 1) + bit, recovery_rate)
        last = 2 * (cells + phases - 1) + bit
        for target, weight in weights:
            edge(last, 2 * target + bit, recovery_rate * weight * retention)
            edge(last, 2 * target + 1 - bit, recovery_rate * weight * (1 - retention))
    q = coo_matrix((values, (rows, columns)), shape=(size, size)).tocsc()
    killed = q.copy().tolil()
    for bit in (0, 1):
        killed[bit, 2 * cells + bit] = 0
    killed = killed.tocsc()
    # Both augmented blocks have a final accumulator. One counts every event,
    # the killed block accumulates only the first future event's positive flux.
    rate_column = csc_matrix(events[:, None])
    zero_row, zero = csc_matrix((1, size)), csc_matrix((1, 1))
    augmented = bmat([[q, rate_column], [zero_row, zero]], format="csc")
    killed_augmented = bmat([[killed, rate_column], [zero_row, zero]], format="csc")
    p = np.zeros(size)
    # Initial bit is known zero, so regeneration's content-retention effect is
    # measurable rather than hidden by a fair-bit marginal.
    for target, weight in weights:
        p[2 * target] = weight
    return dict(Q=q, combined=block_diag((augmented, killed_augmented), format="csc"),
                prior=p, centers=centers, reset=reset, size=size, cells=cells)


def evaluate_grid(cells, horizons):
    started = time.process_time()
    model = independent_generator(cells, BASE_THETA)
    size, n = model["size"], model["cells"]
    initial = np.r_[model["prior"], 0.]
    state = np.r_[initial, initial]
    operator = model["combined"].T
    trace = float(operator.diagonal().sum())
    rows = []
    before = 0.
    for horizon in horizons:
        duration = float(horizon - before)
        state = expm_multiply(duration * operator, state, traceA=duration * trace)
        p, killed = state[:size], state[size + 1:2 * size + 1]
        phases = p.reshape(n + 2, 2)
        mean = phases[:n].sum(1) @ model["centers"] + phases[n:].sum() * model["reset"]
        row = dict(horizon=float(horizon), expected_events=float(state[size]),
                   first_event_probability=float(state[-1]), survival_mass=float(killed.sum()),
                   recovery_mass=float(phases[n:].sum()), mean_log_distance=float(mean),
                   probability_bit_zero=float(phases[:, 0].sum()),
                   total_mass=float(p.sum()), minimum_probability=float(p.min()))
        if abs(row["total_mass"] - 1) > 2e-10 or abs(row["survival_mass"] + row["first_event_probability"] - 1) > 2e-10:
            raise ArithmeticError("Reference mass error exceeds the diagnostic tolerance")
        rows.append(row)
        before = horizon
    return dict(cells=cells, state_count=size, rows=rows, cpu_seconds=time.process_time() - started)


def run(output):
    started, wall = time.process_time(), time.perf_counter()
    horizons = [.15, .45, 1.05, 2.10]
    grids = [evaluate_grid(n, horizons) for n in (8, 16, 32, 64, 256, 512)]
    metrics = ("first_event_probability", "expected_events", "recovery_mass",
               "mean_log_distance", "probability_bit_zero")
    reference = grids[-1]["rows"]
    for grid in grids:
        grid["max_abs_difference_from_512"] = {
            metric: max(abs(row[metric] - ref[metric]) for row, ref in zip(grid["rows"], reference))
            for metric in metrics}
    direct = Cell(DEFAULT_THETA)
    rebuilt = independent_generator(8, BASE_THETA)
    generator_error = float(np.max(np.abs(direct.Q - rebuilt["Q"].toarray())))
    if generator_error > 1e-13:
        raise ArithmeticError("Reconstructed eight-cell reference differs from deployed Q")
    p = rebuilt["prior"]
    deployed_errors = []
    for row in grids[0]["rows"]:
        t = row["horizon"]
        predicted = direct.predict(p, t)
        deployed_errors.extend([abs(float(direct.expected_events(p, t)) - row["expected_events"]),
                                abs(float(direct.first_event_probability(p, t)) - row["first_event_probability"]),
                                abs(float(predicted[16:].sum()) - row["recovery_mass"])])
    result = dict(schema="hcsn-r12-independent-finite-grid-refinement-v1",
                  scope="Sparse finite-grid refinement; no continuum certification or task superiority claim",
                  physical_parameters=BASE_THETA.tolist(), horizons=horizons, grids=grids,
                  fine_reference_cells=512, fine_reference_is_continuum=False,
                  reference_256_to_512_gap=grids[-2]["max_abs_difference_from_512"],
                  deployed_generator_max_abs_error=generator_error,
                  deployed_expm_vs_sparse_reference_max_abs_error=max(deployed_errors),
                  fixed_recovery_law="Erlang(2, mean=.35)", fixed_upper_boundary="reflecting log distance .8",
                  unmeasured_errors=["finite upper-domain truncation vs unbounded process",
                                     "Erlang recovery vs deterministic refractory delay",
                                     "uniform continuum error bound", "task-level filtering/quality error"],
                  cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
                  python=platform.python_version(), energy_joules=None,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  cell_sha256=hashlib.sha256(Path(__file__).with_name("cell.py").read_bytes()).hexdigest())
    output = Path(output)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    result = run(parser.parse_args().output)
    print(json.dumps({"cpu_seconds": result["cpu_seconds"],
                      "deployed_error": result["deployed_expm_vs_sparse_reference_max_abs_error"],
                      "eight_cell_difference": result["grids"][0]["max_abs_difference_from_512"],
                      "reference_gap": result["reference_256_to_512_gap"]}, indent=2))
