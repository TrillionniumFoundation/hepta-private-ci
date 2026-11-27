"""Independent continuous-reference audit for the new 2026-10-29 flow.

The oracle rebuilds parameter transforms, channels, currents and the ODE
in NumPy/SciPy. It never calls the production rhs or production kernels.
These are fresh diagnostic probes, not recovered historical experiments.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.integrate import solve_ivp
from scipy.special import expit
import torch

from .flow import BoundaryFlow


VERSION = "hepta-independent-continuous-audit-20261029-v1"
MODES = ("analytic", "matched_c1", "sigmoid")
STEPS = (0.25, 0.125)
DT = np.array([0.31, 0.73, 1.27, 0.41, 1.11], dtype=np.float64)
DRIVES = np.array([[0, 0, 0], [2, -1, 0.5], [-3, 1, -0.5],
                   [2, -2, 0.25], [-2, 2, -0.25]], dtype=np.float64)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def oracle_channels(x, k, mode):
    """Independent residual/log-sum formula; no production phi kernel."""
    if mode == "sigmoid":
        return expit(k * x), expit(-k * x)
    xp = np.maximum(x, 0)
    xm = np.minimum(x, 0)
    if mode == "matched_c1":
        u2 = k * xp * xp / 2
        return u2 / (1 + u2), np.where(
            x > 0, 1 / ((1 + k) * (1 + k * xp)), 1 - k / ((1 + k) * (1 - xm))
        )
    log_d = np.logaddexp(np.log(k) + xp, -k * xp)
    call = -np.expm1(np.log1p(k) - log_d)
    near = (xp < 1e-3)
    xn = np.where(near, xp, 0)
    numerator = np.zeros_like(xn)
    for j in range(2, 17):
        numerator += (k + (-k) ** j) * xn ** j / math.factorial(j)
    small_call = numerator / (k * np.exp(xn) + np.exp(-k * xn))
    call = np.where(x > 0, np.where(near, small_call, call), 0)
    put = np.where(x > 0, np.exp(-k * xp) / (1 + k), 1 - k * np.exp(xm) / (1 + k))
    return call, put


def oracle_parameters(values, mode):
    p = {"kappa": 0.25 + 3.75 * expit(values["raw.kappa"]),
         "x_star": -0.5 + 2 * expit(values["raw.x_star"]),
         "tau_v": 0.25 + 7.75 * expit(values["raw.tau_v"]),
         "tau_q": 0.25 + 7.75 * expit(values["raw.tau_q"])}
    for name in ("g_call", "g_put", "g_recovery"):
        p[name] = 4 * expit(values["raw." + name])
    lower = p["tau_q"] + 0.25
    p["tau_z"] = lower + (32 - lower) * expit(values["raw.tau_z_fraction"])
    p["log_beta"] = np.log(p["kappa"] / (1 + p["kappa"]))
    p["call_star"], p["put_star"] = oracle_channels(p["x_star"], p["kappa"], mode)
    p["q_star"] = -p["x_star"] - p["log_beta"]
    p["z_star"] = p["g_recovery"] * p["put_star"]
    return p


def oracle_trajectory(values, mode, drives, dts, *, tight=False, offset=None):
    p = oracle_parameters(values, mode)
    state = np.stack([np.zeros_like(p["q_star"]), p["q_star"], p["z_star"]])
    if offset is not None:
        state = state + offset
    trace = [state.copy()]
    for drive, dt in zip(drives, dts):
        iv = 3 * np.tanh(values["drive_v.weight"] @ drive + values["drive_v.bias"])
        iq = 3 * np.tanh(values["drive_q.weight"] @ drive + values["drive_q.bias"])

        def rhs(_time, flat):
            v, q, z = flat.reshape(3, -1)
            a, put = oracle_channels(v - q - p["log_beta"], p["kappa"], mode)
            dq = (-q + p["q_star"] + p["g_call"] * (a - p["call_star"])
                  + p["g_put"] * (put - p["put_star"]) - (z - p["z_star"]) + iq)
            return np.stack([(-v + iv) / p["tau_v"], dq / p["tau_q"],
                             (-z + p["g_recovery"] * put) / p["tau_z"]]).ravel()

        result = solve_ivp(rhs, (0, float(dt)), state.ravel(), method="DOP853",
                           rtol=3e-13 if tight else 1e-11, atol=3e-15 if tight else 1e-13)
        if not result.success:
            raise RuntimeError(result.message)
        state = result.y[:, -1].reshape(3, -1)
        trace.append(state.copy())
    return np.stack(trace)


def model_fixture(mode, case, step):
    torch.manual_seed(20261029)
    model = BoundaryFlow(mode, 3, 2, max_step=step).double()
    with torch.no_grad():
        model.drive_v.weight.copy_(torch.tensor([[0.4, -0.2, 0.1], [-0.3, 0.25, 0.15]]))
        model.drive_q.weight.copy_(torch.tensor([[-0.2, 0.2, 0.1], [0.3, -0.2, -0.1]]))
        if case in ("crossing", "stress"):
            model.raw["x_star"].fill_(math.log(0.3 / 0.7))
        if case == "stress":
            for name in ("tau_v", "tau_q"):
                model.raw[name].fill_(-4)
            model.raw["tau_z_fraction"].fill_(-2.5)
            model.raw["kappa"].fill_(1.5)
            for name in ("g_call", "g_put", "g_recovery"):
                model.raw[name].fill_(1.2)
    return model


def snapshot(model):
    return {name: value.detach().cpu().numpy().copy() for name, value in model.named_parameters()}


def numpy_loss(trace):
    weights = np.linspace(-0.7, 0.9, trace.size).reshape(trace.shape)
    return float((weights * trace).sum() / trace.shape[0] + 0.03 * (trace * trace).mean())


def torch_trajectory(model, drives, dts, offset=None):
    dtype = next(model.parameters()).dtype
    state = model.initial_state(1)
    if offset is not None:
        extra = torch.as_tensor(offset, dtype=dtype)
        state = tuple(value + extra[j] for j, value in enumerate(state))
    trace = [torch.stack(state)[:, 0]]
    for drive, dt in zip(drives, dts):
        state, _, _ = model.step(torch.as_tensor(drive, dtype=dtype)[None], float(dt), state)
        trace.append(torch.stack(state)[:, 0])
    return torch.stack(trace)


def directional_gradient(model, drives, dts, directions):
    trace = torch_trajectory(model, drives, dts)
    weights = torch.linspace(-0.7, 0.9, trace.numel(), dtype=trace.dtype).reshape(trace.shape)
    loss = (weights * trace).sum() / trace.shape[0] + 0.03 * trace.square().mean()
    gradients = torch.autograd.grad(loss, tuple(model.parameters()))
    flat = torch.cat([g.reshape(-1) for g in gradients]).detach().cpu().numpy()
    return trace.detach().cpu().numpy(), directions @ flat


def perturb(values, direction, scale):
    result, position = {}, 0
    for name, value in values.items():
        result[name] = value + scale * direction[position:position + value.size].reshape(value.shape)
        position += value.size
    return result


def oracle_directions(values, mode, drives, directions, epsilon):
    return np.array([
        (numpy_loss(oracle_trajectory(perturb(values, direction, epsilon), mode, drives, DT, tight=True))
         - numpy_loss(oracle_trajectory(perturb(values, direction, -epsilon), mode, drives, DT, tight=True)))
        / (2 * epsilon) for direction in directions
    ])


def scaled_state_error(observed, reference):
    return float(np.max(np.abs(observed - reference) / (1 + np.abs(reference))))


def relative_gradient_error(observed, reference):
    return float(np.linalg.norm(observed - reference) / max(1e-8, np.linalg.norm(reference)))


def structural_checks(mode):
    model = model_fixture(mode, "crossing", 0.25)
    drive = torch.tensor([[1.1, -0.4, 0.7]], dtype=torch.float64)
    state = model.initial_state(1)
    alone = model.step(drive, 0.31, state)[0]
    mixed = model.step(torch.cat([drive, -drive]), torch.tensor([0.31, 2.83], dtype=torch.float64),
                       model.initial_state(2))[0]
    zero = model.step(drive, 0, state)[0]
    batch_error = max(float((a - b[:1]).abs().max().detach()) for a, b in zip(alone, mixed))
    zero_error = max(float((a - b).abs().max().detach()) for a, b in zip(state, zero))
    return {"batch_composition_max_abs": batch_error, "zero_dt_max_abs": zero_error,
            "passed": batch_error <= 1e-14 and zero_error == 0}


def audit(out):
    out.mkdir(parents=True, exist_ok=True)
    if (out / "protocol.json").exists():
        raise FileExistsError("Use a fresh audit directory; existing predeclarations must be preserved")
    root = Path(__file__).resolve().parent
    sources = {name: sha(root / name) for name in ("audit.py", "flow.py", "numerics.py")}
    protocol = {
        "version": VERSION, "scope": "New independent diagnostics; no historical run recovery",
        "sources_sha256": sources, "sealed_before_evaluation_unix": time.time(),
        "candidate_steps_in_order": STEPS, "qualification_cases": ["default", "crossing"],
        "modes": MODES, "default_drives": (0.35 * DRIVES).tolist(),
        "crossing_drives": DRIVES.tolist(), "durations": DT.tolist(),
        "directions": {"count": 4, "seed": 20261029, "distribution": "normalized iid standard normal"},
        "thresholds": {"scaled_state_max": 1e-3, "directional_gradient_l2_relative": 1e-2,
                       "oracle_scaled_state_change": 1e-8, "oracle_fd_gradient_relative_change": 1e-4,
                       "same_step_dtype_scaled_state": 1e-5, "same_step_dtype_gradient_relative": 1e-4},
        "oracle": {"method": "independently rederived NumPy RHS, SciPy DOP853", "rtol": 1e-11,
                   "atol": 1e-13, "tight_rtol": 3e-13, "tight_atol": 3e-15,
                   "finite_difference_epsilons": [1e-5, 5e-6]},
        "decision": "First candidate passing every qualification case and structural check; no task scores",
        "stress_scope": "Interior stiff parameters and invariant-rectangle edge states; report only, not domain certificate",
        "limitations": ["Four directional derivatives do not certify the full gradient",
                        "Local probes do not guarantee every learned parameter trajectory",
                        "Adaptive numerical reference and finite differences have finite tolerances"],
    }
    (out / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n")
    arrays, records = {}, []
    structure = {mode: structural_checks(mode) for mode in MODES}
    for mode in MODES:
        for case in ("default", "crossing"):
            drives = DRIVES * (0.35 if case == "default" else 1)
            fixture = model_fixture(mode, case, STEPS[0])
            values = snapshot(fixture)
            size = sum(v.size for v in values.values())
            directions = np.random.default_rng(20261029).normal(size=(4, size))
            directions /= np.linalg.norm(directions, axis=1, keepdims=True)
            reference = oracle_trajectory(values, mode, drives, DT)
            tight = oracle_trajectory(values, mode, drives, DT, tight=True)
            fd_coarse = oracle_directions(values, mode, drives, directions, 1e-5)
            fd_fine = oracle_directions(values, mode, drives, directions, 5e-6)
            oracle_change = scaled_state_error(reference, tight)
            fd_change = relative_gradient_error(fd_coarse, fd_fine)
            prefix = mode + "__" + case
            arrays[prefix + "__reference"] = reference
            arrays[prefix + "__reference_tight"] = tight
            arrays[prefix + "__directions"] = directions
            arrays[prefix + "__fd_coarse"] = fd_coarse
            arrays[prefix + "__fd_fine"] = fd_fine
            p = oracle_parameters(values, mode)
            margin = tight[:, 0] - tight[:, 1] - p["log_beta"]
            for step in STEPS:
                model = model_fixture(mode, case, step)
                trace, gradient = directional_gradient(model, drives, DT, directions)
                trace32, gradient32 = directional_gradient(model.float(), drives, DT, directions)
                state_error = scaled_state_error(trace, tight)
                grad_error = relative_gradient_error(gradient, fd_fine)
                dtype_state = scaled_state_error(trace32, trace)
                dtype_gradient = relative_gradient_error(gradient32, gradient)
                record = {"mode": mode, "case": case, "max_step": step,
                          "state_scaled_max": state_error, "gradient_l2_relative": grad_error,
                          "oracle_state_change": oracle_change, "oracle_fd_gradient_change": fd_change,
                          "same_step_dtype_state": dtype_state, "same_step_dtype_gradient": dtype_gradient,
                          "sampled_margin_range": [float(margin.min()), float(margin.max())]}
                record["passed"] = (state_error <= 1e-3 and grad_error <= 1e-2
                                    and oracle_change <= 1e-8 and fd_change <= 1e-4
                                    and dtype_state <= 1e-5 and dtype_gradient <= 1e-4)
                records.append(record)
                key = prefix + "__h" + str(step).replace(".", "p")
                arrays[key + "__fp64"] = trace
                arrays[key + "__fp32"] = trace32
                arrays[key + "__gradient_fp64"] = gradient
                arrays[key + "__gradient_fp32"] = gradient32
                print(json.dumps(record), flush=True)
    selected = next((step for step in STEPS if all(r["passed"] for r in records if r["max_step"] == step)
                     and all(r["passed"] for r in structure.values())), None)
    stress = []
    for mode in MODES:
        model = model_fixture(mode, "stress", selected or STEPS[-1])
        values = snapshot(model)
        p = oracle_parameters(values, mode)
        # Each component lies on its invariant rectangle's face.
        offset = np.array([[3.0, -3.0], [15.0, -15.0], [0, 4]])
        offset[2] -= p["z_star"]
        reference = oracle_trajectory(values, mode, DRIVES, DT, tight=True, offset=offset)
        trace = torch_trajectory(model, DRIVES, DT, offset=offset).detach().numpy()
        limits = {"v_abs": float(np.max(np.abs(trace[:, 0]))),
                  "q_offset_abs": float(np.max(np.abs(trace[:, 1] - p["q_star"]))),
                  "z_min": float(trace[:, 2].min()), "z_max": float(trace[:, 2].max())}
        stress.append({"mode": mode, "max_step": model.max_step,
                       "scaled_state_error": scaled_state_error(trace, reference),
                       "finite": bool(np.isfinite(trace).all()), "bounds_observed": limits})
        arrays[mode + "__stress_reference"] = reference
        arrays[mode + "__stress_etd"] = trace
    unchanged = all(sha(root / name) == value for name, value in sources.items())
    np.savez_compressed(out / "raw_arrays.npz", **arrays)
    result = {"version": VERSION, "source_unchanged_during_audit": unchanged,
              "selected_step": selected, "passed": selected is not None and unchanged,
              "qualification": records, "structural": structure, "stress_report_only": stress,
              "protocol_sha256": sha(out / "protocol.json"), "raw_arrays_sha256": sha(out / "raw_arrays.npz")}
    (out / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"selected_step": selected, "passed": result["passed"], "out": str(out)}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    audit(args.out)


if __name__ == "__main__":
    main()
