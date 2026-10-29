"""Compare endpoint-frozen memory with an independently integrated joint ODE.

This untrained constant-forcing probe is separate from the registered token
tasks. It does not change their model, data, selection or reported scores.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np
from scipy.integrate import solve_ivp
import torch
from torch.nn import functional as F

from experiments.call_put_stable_flow.flow import BoundaryFlow
from experiments.call_put_stable_flow.memory import exact_delta_step


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def independent_channels(x, mode):
    if mode == "analytic":
        return (
            (1 - 1 / np.cosh(x), 0.5 * np.exp(-x))
            if x > 0
            else (0.0, 1 - 0.5 * np.exp(x))
        )
    return (x * x / (2 + x * x), 0.5 / (1 + x)) if x > 0 else (0.0, 1 - 0.5 / (1 - x))


def configure(mode, step):
    model = BoundaryFlow(mode, 1, 1, max_step=step).double()
    values = {
        "kappa": (1.0, 0.25, 4.0),
        "x_star": (0.5, -0.5, 1.5),
        "tau_v": (1.0, 0.25, 8.0),
        "tau_q": (1.5, 0.25, 8.0),
        "tau_z_fraction": (6.0, 1.75, 32.0),
        "g_call": (1.0, 0.0, 4.0),
        "g_put": (2.0, 0.0, 4.0),
        "g_recovery": (2.0, 0.0, 4.0),
    }
    with torch.no_grad():
        for name, (value, low, high) in values.items():
            f = (value - low) / (high - low)
            model.raw[name].fill_(math.log(f / (1 - f)))
        for projection, current in ((model.drive_v, 1.2), (model.drive_q, -0.5)):
            projection.weight.zero_()
            projection.bias.fill_(math.atanh(current / 3))
    return model


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    protocol = {
        "schema": "hepta-untrained-coupling-error-v1",
        "created_unix": time.time(),
        "purpose": "Separate boundary internal mesh error from endpoint-frozen memory coupling error",
        "modes": ["analytic", "matched_c1"],
        "duration": 8.0,
        "outer_steps": [1.0, 0.5, 0.25, 0.125],
        "internal_steps": [0.0625, 0.03125],
        "key": [0.6, 0.8, 0.0],
        "value": [1.0, -0.5, 0.2, 0.0],
        "initial_memory": "zeros(4,3)",
        "forcing": {"I_v": 1.2, "I_b": -0.5},
        "flow": {
            "kappa": 1.0,
            "x_star": 0.5,
            "tau_v": 1.0,
            "tau_q": 1.5,
            "tau_z": 6.0,
            "g_call": 1.0,
            "g_put": 2.0,
            "g_recovery": 2.0,
        },
        "rates": {
            "leak": "softplus(-3 - 1.2*(Call-Call_star))",
            "write": "softplus(1.1*(Put-Put_star))",
        },
        "independent_reference": "Joint v/q/z/M NumPy RHS; DOP853 rtol2e-11 atol2e-13, repeated at 2e-12/2e-14",
        "reference_scaled_max_tolerance": 1e-8,
        "interpretation": "A distinct constant physical forcing, with no parser or token replay. Numerical comparison, not a trained task, hyperparameter selection or replacement score.",
        "source_sha256": digest(Path(__file__)),
        "formal_data_or_checkpoint_read": False,
    }
    shutil.copyfile(Path(__file__), output / "coupling_diagnostic.py")
    write_json(output / "protocol.json", protocol)
    torch.set_num_threads(1)
    key, value = np.array(protocol["key"]), np.array(protocol["value"])
    qt = -0.5 - math.log(0.5)
    rows, arrays = [], {}
    for mode in protocol["modes"]:
        astar, pstar = independent_channels(0.5, mode)
        initial = np.r_[0.0, qt, 2 * pstar, np.zeros(12)]

        def rhs(_t, y):
            v, q, z = y[:3]
            a, p = independent_channels(v - q - math.log(0.5), mode)
            leak, write = (
                np.logaddexp(0, -3 - 1.2 * (a - astar)),
                np.logaddexp(0, 1.1 * (p - pstar)),
            )
            memory = y[3:].reshape(4, 3)
            dm = -leak * memory + write * np.outer(value - memory @ key, key)
            return np.r_[
                -v + 1.2,
                (-q + qt + a - astar + 2 * (p - pstar) - (z - 2 * pstar) - 0.5) / 1.5,
                (-z + 2 * p) / 6,
                dm.ravel(),
            ]

        times = np.arange(0, 8.0625, 0.125)
        refs = [
            solve_ivp(
                rhs,
                (0, 8),
                initial,
                method="DOP853",
                t_eval=times,
                rtol=rtol,
                atol=rtol * 0.01,
            )
            for rtol in (2e-11, 2e-12)
        ]
        if not all(r.success for r in refs):
            raise RuntimeError("Independent joint reference failed")
        reference = refs[1].y.T
        consistency = float(
            np.max(np.abs(refs[0].y.T - reference) / (1 + np.abs(reference)))
        )
        arrays[mode + "_reference"] = reference
        arrays[mode + "_reference_looser"] = refs[0].y.T
        rows.append(
            {
                "mode": mode,
                "reference_scaled_consistency": consistency,
                "reference_resolved": consistency
                <= protocol["reference_scaled_max_tolerance"],
            }
        )
        for dt in protocol["outer_steps"]:
            for h in protocol["internal_steps"]:
                model = configure(mode, h)
                k = torch.tensor(key, dtype=torch.float64).reshape(1, 1, 3)
                u = torch.tensor(value, dtype=torch.float64).reshape(1, 1, 4)
                drive = torch.zeros((1, 1), dtype=torch.float64)
                delta = torch.full((1, int(round(8 / dt))), dt, dtype=torch.float64)
                with torch.no_grad():
                    prepared = model.prepare_sequence(delta)
                    state = model.initial_state(
                        1, dtype=torch.float64, prepared=prepared
                    )
                    memory = torch.zeros((1, 1, 4, 3), dtype=torch.float64)
                    trace = [initial.copy()]
                    for index in range(delta.shape[1]):
                        state, a, p = model.step_prepared(drive, state, prepared, index)
                        leak = F.softplus(-3 - 1.2 * (a - astar))
                        write = F.softplus(1.1 * (p - pstar))
                        memory = exact_delta_step(
                            memory, k, u, leak, write, delta[:, index]
                        )
                        trace.append(
                            np.r_[[s.item() for s in state], memory.numpy().ravel()]
                        )
                trace = np.asarray(trace)
                aligned = reference[:: round(dt / 0.125)]
                diff = np.abs(trace - aligned) / (1 + np.abs(aligned))
                arrays[f"{mode}_dt{dt}_h{h}"] = trace
                rows.append(
                    {
                        "mode": mode,
                        "outer_step": dt,
                        "inner_step": h,
                        "flow_scaled_max_error": float(diff[:, :3].max()),
                        "memory_scaled_max_error": float(diff[:, 3:].max()),
                        "terminal_memory_l2_error": float(
                            np.linalg.norm(trace[-1, 3:] - aligned[-1, 3:])
                        ),
                        "reference_resolved": consistency
                        <= protocol["reference_scaled_max_tolerance"],
                    }
                )
    arrays["reference_times"] = times
    with (output / "raw_arrays.npz").open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    result = {
        "status": "complete",
        "protocol_sha256": digest(output / "protocol.json"),
        "raw_arrays_sha256": digest(output / "raw_arrays.npz"),
        "rows": rows,
        "claim_limit": "Only the registered constant-forcing untrained probe. Inner-mesh convergence does not by itself certify a full continuously coupled model.",
    }
    write_json(output / "results.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
