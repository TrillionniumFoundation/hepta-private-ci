"""Predeclared, untrained planar feedback diagnostic; never a task result."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np
from scipy.integrate import solve_ivp
from scipy.signal import find_peaks
import torch

from experiments.call_put_stable_flow.flow import BoundaryFlow


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def channels(x):
    # Independent kappa=1 formula; cancellation here is quadratic and harmless
    # for the RHS reference's declared absolute tolerance and modest state range.
    return (
        (1.0 - 1.0 / np.cosh(x), 0.5 * np.exp(-x))
        if x > 0
        else (
            0.0,
            1.0 - 0.5 * np.exp(x),
        )
    )


def rhs(_time, yz, gain):
    q, z = yz
    a, p = channels(-q - math.log(0.5))
    return [
        -q - math.log(0.5) + a + gain * (p - 0.5) - (z - gain * 0.5),
        (-z + gain * p) / 6.0,
    ]


def build(gain, step):
    model = BoundaryFlow("analytic", 1, 1, max_step=step).double()
    values = {
        "kappa": (1.0, 0.25, 4.0),
        "x_star": (0.0, -0.5, 1.5),
        "tau_v": (1.0, 0.25, 8.0),
        "tau_q": (1.0, 0.25, 8.0),
        "tau_z_fraction": (6.0, 1.25, 32.0),
        "g_call": (1.0, 0.0, 4.0),
        "g_put": (gain, 0.0, 4.0),
        "g_recovery": (gain, 0.0, 4.0),
    }
    with torch.no_grad():
        for name, (value, low, high) in values.items():
            fraction = (value - low) / (high - low)
            model.raw[name].fill_(math.log(fraction / (1.0 - fraction)))
        for projection in (model.drive_v, model.drive_q):
            projection.weight.zero_()
            projection.bias.zero_()
    return model


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve()
    protocol = {
        "schema": "hepta-untrained-planar-feedback-diagnostic-v1",
        "purpose": "Establish possible decay and autonomous oscillatory regimes, not trained spiking or accuracy",
        "cases": {"restoring": 1.5, "regenerative_recovery": 3.0},
        "parameters": {
            "kappa": 1.0,
            "x_star": 0.0,
            "g_call": 1.0,
            "tau_q": 1.0,
            "tau_z": 6.0,
            "g_recovery": "equals g_put",
            "v": 0.0,
            "external_drive": 0.0,
        },
        "initial_q_offset": 0.02,
        "duration": 180.0,
        "external_step": 0.125,
        "internal_steps": [0.0625, 0.03125],
        "tail_start": 90.0,
        "reference": "Independent NumPy RHS with DOP853 rtol=2e-11 atol=2e-13; no production RHS",
        "verification_gate_scaled_max_state_error": 0.005,
        "source_sha256": digest(source),
        "registered_before_simulation_unix": time.time(),
        "uses_formal_data_or_trained_checkpoints": False,
        "source_formula": "kappa=1 normalized Call=1-sech(x) for x>0, zero otherwise; normalized Put piecewise exponential",
    }
    shutil.copyfile(source, output / "phase_dynamics.py")
    write_json(output / "protocol.json", protocol)
    times = np.arange(0.0, protocol["duration"] + 0.0625, 0.125)
    arrays, rows = {"times": times}, []
    torch.set_num_threads(1)
    for name, gain in protocol["cases"].items():
        initial = np.array([-math.log(0.5) + 0.02, gain * 0.5])
        oracle = solve_ivp(
            lambda t, y: rhs(t, y, gain),
            (times[0], times[-1]),
            initial,
            t_eval=times,
            method="DOP853",
            rtol=2e-11,
            atol=2e-13,
        )
        if not oracle.success:
            raise RuntimeError(oracle.message)
        reference = oracle.y.T
        arrays[name + "_reference_qz"] = reference
        jacobian = np.array([[-1 + gain / 2, -1], [gain / 12, -1 / 6]])
        eigenvalues = np.linalg.eigvals(jacobian)
        tail = times >= protocol["tail_start"]
        margin = -reference[:, 0] - math.log(0.5)
        peaks, _ = find_peaks(margin[tail], prominence=0.001)
        peak_times = times[tail][peaks]
        rows.append(
            {
                "case": name,
                "put_recovery_gain": gain,
                "jacobian": jacobian.tolist(),
                "trace": float(np.trace(jacobian)),
                "determinant": float(np.linalg.det(jacobian)),
                "eigenvalues": [[float(v.real), float(v.imag)] for v in eigenvalues],
                "tail_margin_peak_to_peak": float(np.ptp(margin[tail])),
                "tail_peak_times": peak_times.tolist(),
                "mean_peak_interval": float(np.diff(peak_times).mean())
                if len(peaks) > 1
                else None,
            }
        )
        for step in protocol["internal_steps"]:
            model = build(gain, step)
            dt = torch.full((1, len(times) - 1), 0.125, dtype=torch.float64)
            drive = torch.zeros((1, 1), dtype=torch.float64)
            with torch.no_grad():
                prepared = model.prepare_sequence(dt)
                state = model.initial_state(1, dtype=torch.float64, prepared=prepared)
                state = (state[0], state[1] + 0.02, state[2])
                trajectory = [np.array([state[1].item(), state[2].item()])]
                for index in range(len(times) - 1):
                    state, _, _ = model.step_prepared(drive, state, prepared, index)
                    trajectory.append(np.array([state[1].item(), state[2].item()]))
            trajectory = np.asarray(trajectory)
            arrays[f"{name}_h{step}_qz"] = trajectory
            error = float(
                np.max(np.abs(trajectory - reference) / (1 + np.abs(reference)))
            )
            rows.append(
                {
                    "case": name,
                    "internal_step": step,
                    "scaled_max_state_error": error,
                    "reference_gate_passed": error
                    <= protocol["verification_gate_scaled_max_state_error"],
                }
            )
    with (output / "raw_arrays.npz").open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    result = {
        "status": "complete",
        "protocol_sha256": digest(output / "protocol.json"),
        "raw_arrays_sha256": digest(output / "raw_arrays.npz"),
        "rows": rows,
        "interpretation": "Hand-selected bounded parameters demonstrate regime capacity only. Threshold crossings are continuous; no hard reset, event sparsity, biological spike fit, or trained task improvement is established.",
    }
    write_json(output / "results.json", result)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
