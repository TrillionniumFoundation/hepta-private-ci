"""New, untrained flow qualification. Run from repository root with --output."""

import argparse
import copy
import datetime
import hashlib
import json
from pathlib import Path
import platform
import shutil
import time

import numpy as np
import torch

from experiments.call_put_stable_flow.flow import BoundaryFlow, FLOW_VERSION
from experiments.call_put_stable_flow.numerics import call_put, phi1, phi2
from experiments.call_put_stable_flow.tests.test_numerics import option_reference, phi_reference


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def probe(model, label):
    dtype = next(model.parameters()).dtype
    smooth = [[[0.4, -0.2], [-0.7, 0.3]], [[0.1, 0.3], [-0.4, 0.2]],
              [[-0.2, 0.2], [0.3, -0.1]]]
    crossing = [[[3., -2.], [-3., 2.]], [[-3., 2.], [3., -2.]],
                [[3., -2.], [-3., 2.]]]
    drive = torch.tensor(smooth if label == "smooth" else crossing, dtype=torch.float32).to(dtype)
    dt = torch.tensor([[0.2, 0.5], [0.5, 0.75], [0.75, 0.25]], dtype=torch.float32).to(dtype)
    state = model.initial_state(2)
    states = [torch.stack(state)]
    for input_value, times in zip(drive, dt):
        state, a, p = model.step(input_value, times, state)
        states.append(torch.stack(state))
    weights = torch.tensor([[1., 0.7], [0.3, 1.1]], dtype=torch.float32).to(dtype)
    objective = ((0.7 * state[0] + 0.3 * state[1] + 0.2 * state[2] + 0.4 * a - 0.6 * p) * weights).sum()
    gradients = torch.autograd.grad(objective, tuple(model.parameters()))
    return {"value": objective.detach().double().numpy(),
            "gradient": torch.cat([g.flatten() for g in gradients]).detach().double().numpy(),
            "states": torch.stack(states).detach().double().numpy(),
            "drive": drive.detach().double().numpy(), "dt": dt.detach().double().numpy()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output
    destination.mkdir(parents=True, exist_ok=False)
    repository = Path.cwd()
    sources = [repository / "experiments/call_put_stable_flow" / part for part in
               ["numerics.py", "flow.py", "tests/test_numerics.py", "tests/test_flow.py"]]
    sources.append(Path(__file__).resolve())
    snapshot = destination / "source"
    snapshot.mkdir()
    hashes = {}
    for source in sources:
        shutil.copyfile(source, snapshot / source.name)
        hashes[str(source.relative_to(repository))] = digest(source)
    protocol = {
        "identity": "new-untrained-stable-flow-qualification-20261029-v1",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "flow_version": FLOW_VERSION,
        "not_recovered_checkpoint": True,
        "source_sha256": hashes,
        "kernel_tolerances": {"float32_relative": 1e-5, "float64_relative": 1e-11,
                              "subnormal_absolute_floor": "16*dtype.tiny"},
        "precision_control": "weights, inputs, dt initialized in FP32 then exactly upcast",
        "phi_grid": [-20, -4, -1.0000001, -1, -0.2500001, -0.25, -0.1, -1e-4,
                     -1e-8, 0, 1e-8, 1e-4, 0.25, 0.2500001, 1, 1.0000001, 4, 20],
        "option_x_grid": [-20, -0.25, -1e-8, 0, 1e-12, 1e-8, 1e-4, 0.01,
                          0.0625, 0.250001, 0.5, 2, 20, 80],
        "kappa_grid": [0.25, 1.0, 4.0],
        "fp32_steps": [0.25, 0.125, 0.0625],
        "fp64_steps": [0.25, 0.125, 0.0625, 0.03125, 0.015625, 0.0078125, 0.00390625],
        "flow_modes": ["analytic", "matched_c1", "sigmoid"],
        "probe_labels": ["smooth", "crossing"],
        "interpretation": "Kernel gates are assertions; flow curves are diagnostics, not a global error certificate or task-quality result.",
        "torch_version": torch.__version__, "numpy_version": np.__version__,
        "python_version": platform.python_version(), "threads": 1,
    }
    write_json(destination / "PROTOCOL.json", protocol)
    torch.set_num_threads(1)
    started = time.process_time()
    records = []
    for dtype in [torch.float32, torch.float64]:
        limit = 1e-5 if dtype == torch.float32 else 1e-11
        tiny = 16 * torch.finfo(dtype).tiny
        for order, function in [(1, phi1), (2, phi2)]:
            for value in protocol["phi_grid"]:
                z = torch.tensor(value, dtype=dtype, requires_grad=True)
                y = function(z)
                derivative, = torch.autograd.grad(y, z)
                reference = phi_reference(float(z.detach()), order)
                actual = [float(y.detach()), float(derivative)]
                errors = [abs(a - b) / max(abs(b), tiny) for a, b in zip(actual, reference)]
                assert max(errors) <= limit
                records.append({"kernel": f"phi{order}", "dtype": str(dtype), "input": float(z.detach()),
                                "actual": actual, "reference": reference, "relative_errors": errors})
        for k in protocol["kappa_grid"]:
            for value in protocol["option_x_grid"]:
                x = torch.tensor(value, dtype=dtype, requires_grad=True)
                kappa = torch.tensor(k, dtype=dtype, requires_grad=True)
                a, p = call_put(x, kappa)
                ax, ak = torch.autograd.grad(a, (x, kappa), retain_graph=True)
                px, pk = torch.autograd.grad(p, (x, kappa))
                actual = [float(t.detach()) for t in (a, p, ax, ak, px, pk)]
                reference = option_reference(float(x.detach()), float(kappa.detach()))
                errors = [abs(a - b) / max(abs(b), tiny) for a, b in zip(actual, reference)]
                assert all(abs(a - b) <= tiny or error <= limit
                           for a, b, error in zip(actual, reference, errors))
                records.append({"kernel": "analytic_call_put", "dtype": str(dtype),
                                "input": [float(x.detach()), float(kappa.detach())],
                                "actual": actual, "reference": reference, "relative_errors": errors})
    write_json(destination / "KERNEL_RAW.json", records)
    arrays = {}
    flow_records = []
    for mode in protocol["flow_modes"]:
        torch.manual_seed(8301)
        initial = BoundaryFlow(mode, 2, 2, max_step=0.25).float()
        with torch.no_grad():
            initial.drive_v.weight.copy_(torch.tensor([[0.15, -0.2], [0.4, 0.1]]))
            initial.drive_q.weight.copy_(torch.tensor([[0.1, 0.05], [-0.1, 0.2]]))
        for name, parameter in initial.named_parameters():
            arrays[f"initial__{mode}__{name}"] = parameter.detach().numpy()
        for label in protocol["probe_labels"]:
            outputs = {}
            for dtype, steps in [(torch.float32, protocol["fp32_steps"]),
                                 (torch.float64, protocol["fp64_steps"])]:
                for h in steps:
                    model = copy.deepcopy(initial).to(dtype=dtype)
                    model.max_step = h
                    data = probe(model, label)
                    identifier = f"{mode}__{label}__{str(dtype)}__{h}"
                    for name, value in data.items():
                        arrays[f"{identifier}__{name}"] = value
                    outputs[str(dtype), h] = data
            fine = outputs["torch.float64", protocol["fp64_steps"][-1]]
            for (dtype, h), data in outputs.items():
                ref = outputs["torch.float64", h] if dtype == "torch.float32" else fine
                gradient_norm = np.linalg.norm(ref["gradient"])
                flow_records.append({"mode": mode, "probe": label, "dtype": dtype, "h": h,
                    "comparison": "same_h_fp32_minus_fp64" if dtype == "torch.float32" else "fp64_h_minus_finest",
                    "reference_h": h if dtype == "torch.float32" else protocol["fp64_steps"][-1],
                    "objective": float(data["value"]),
                    "objective_absolute_difference": float(abs(data["value"] - ref["value"])),
                    "state_max_absolute_difference": float(np.max(abs(data["states"] - ref["states"]))),
                    "gradient_relative_l2_difference": float(np.linalg.norm(data["gradient"] - ref["gradient"]) / gradient_norm),
                    "reference_gradient_l2_norm": float(gradient_norm),
                    "gradient_cosine": float(np.dot(data["gradient"], ref["gradient"]) / (np.linalg.norm(data["gradient"]) * gradient_norm))})
    np.savez_compressed(destination / "FLOW_RAW.npz", **arrays)
    write_json(destination / "FLOW_COMPARISONS.json", flow_records)
    result = {"identity": protocol["identity"], "kernel_rows": len(records), "flow_rows": len(flow_records),
              "cpu_seconds": time.process_time() - started,
              "source_sha256": hashes,
              "artifacts": {p.name: digest(p) for p in destination.iterdir() if p.is_file()}}
    write_json(destination / "RESULTS.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
