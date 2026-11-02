"""Source-frozen, same-weight numerical and whole-model timing comparison."""

import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import time

import numpy as np
from scipy.linalg import expm
import scipy
import torch
from torch.nn import functional as F

from experiments.hcsn_addressed_flow_20261101 import addressed_models, data
from experiments.hcsn_four_stage_flow_20261031.models import ContentModel
from experiments.hcsn_four_stage_flow_20261031.operator_audit import independent_generator
from . import fused_addressed


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PROTOCOL = json.loads((HERE / "PROTOCOL.json").read_text())
DEPENDENCIES = [HERE / "audit.py", HERE / "fused_addressed.py", HERE / "PROTOCOL.json",
                Path(addressed_models.__file__), Path(data.__file__),
                ROOT / "experiments/hcsn_four_stage_flow_20261031/models.py",
                ROOT / "experiments/hcsn_four_stage_flow_20261031/marked_flow.py",
                ROOT / "experiments/hcsn_four_stage_flow_20261031/operator_audit.py",
                ROOT / "experiments/hcsn_four_stage_flow_20261031/synthetic_data.py",
                ROOT / "experiments/hcsn_four_stage_flow_20261031/extended_eval.py",
                ROOT / "experiments/hcsn_distributional_v2/distribution_kernel.py"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity():
    return {str(p.relative_to(ROOT)): digest(p) for p in DEPENDENCIES}


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def checkpoint(task):
    return HERE / "checkpoints" / f"{task}_flow.pt"


def freeze():
    frozen = dict(schema="hcsn.addressed-preparation.freeze.v1",
                  created_unix_ns=time.time_ns(), source=source_identity(),
                  checkpoints={task: digest(checkpoint(task)) for task in PROTOCOL["tasks"]},
                  protocol_sha256=digest(HERE / "PROTOCOL.json"))
    write(HERE / "SOURCE_FREEZE.json", frozen)
    return frozen


def backend(name):
    return fused_addressed.addressed_only() if name == "fused" else contextlib.nullcontext()


def independent_matrices(model, arrays):
    """NumPy physical assembly and SciPy expm; no Torch generator assembler."""
    x, dt, observed = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed")]
    with torch.no_grad():
        encoded = model.encode(x)
        proposed = model.control(encoded).double().numpy()
        actual = fused_addressed.prepare(model, encoded, dt, observed)
    physical = model.physical.detach().double().numpy()
    sigmoid = lambda x: 1 / (1 + np.exp(-x))
    sigma, tau = .15 + .4 * sigmoid(physical[0]), .15 + .7 * sigmoid(physical[1])
    eta, decay = sigmoid(physical[3]), .05 * sigmoid(physical[4])
    rows = []
    for b in range(min(3, len(x))):
        previous = np.zeros(2)
        for t in range(x.shape[1]):
            boundary = .6 + .8 * sigmoid(previous[0])
            mu = .05 + .9 * sigmoid(previous[1] + physical[2])
            case = dict(parameters=[mu, sigma, boundary, -.5, tau],
                        cells=4, phases=1, lower=-1.5)
            q, mark, _, _ = independent_generator(case)
            for key, generator in (("P", q), ("T", q - (1 - eta) * mark - decay * np.eye(5))):
                error = float(np.max(np.abs(actual[key][b, t].numpy() - expm(generator * float(dt[b, t])))))
                rows.append(dict(row=b, step=t, matrix=key, max_absolute_error=error,
                                 passed=error <= PROTOCOL["scipy_matrix_atol"]))
            if observed[b, t]:
                previous = proposed[b, t]
    return rows


def numerical(model, arrays):
    x, dt, seen = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed")]
    labels = torch.from_numpy(arrays["y"])
    outputs, gradients = {}, {}
    for name in ("dense", "fused"):
        model.zero_grad(set_to_none=True)
        with backend(name):
            output = model(x, dt, seen)
            F.cross_entropy(output.flatten(0, 1), labels.flatten()).backward()
        outputs[name] = output.detach().numpy()
        gradients[name] = {key: p.grad.detach().numpy().copy() for key, p in model.named_parameters()
                           if p.grad is not None}
    output_error = float(np.max(np.abs(outputs["dense"] - outputs["fused"])))
    same_gradient_keys = set(gradients["dense"]) == set(gradients["fused"])
    gradient_errors = {key: float(np.max(np.abs(gradients["dense"][key] - gradients["fused"][key])))
                       for key in gradients["dense"]} if same_gradient_keys else {}
    gradient_error = max(gradient_errors.values(), default=float("inf"))
    return dict(output_error=output_error, parameter_gradient_error=gradient_error,
                per_parameter_errors=gradient_errors, same_gradient_keys=same_gradient_keys,
                argmax_identical=bool(np.array_equal(outputs["dense"].argmax(-1), outputs["fused"].argmax(-1))),
                passed=same_gradient_keys and output_error <= PROTOCOL["numerical_output_atol"]
                and gradient_error <= PROTOCOL["parameter_gradient_atol"])


def benchmark(model, arrays, backward, seed):
    x, dt, seen = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed")]
    labels = torch.from_numpy(arrays["y"])
    samples = {"dense": [], "fused": []}
    order = []
    rng = random.Random(seed)
    for iteration in range(PROTOCOL["warmups"] + PROTOCOL["repeats"]):
        names = rng.sample(["dense", "fused"], 2)
        if iteration >= PROTOCOL["warmups"]:
            order.append(names)
        for name in names:
            model.zero_grad(set_to_none=True)
            started = time.perf_counter_ns()
            with backend(name), torch.set_grad_enabled(backward):
                output = model(x, dt, seen)
                if backward:
                    F.cross_entropy(output.flatten(0, 1), labels.flatten()).backward()
            elapsed = (time.perf_counter_ns() - started) * 1e-9
            if iteration >= PROTOCOL["warmups"]:
                samples[name].append(elapsed)
    medians = {name: statistics.median(values) for name, values in samples.items()}
    return dict(backward=backward, raw_seconds=samples, order=order,
                median_seconds=medians, dense_over_fused=medians["dense"] / medians["fused"])


def run(phase, out):
    torch.set_num_threads(1)
    out.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((HERE / "SOURCE_FREEZE.json").read_text()) if phase == "confirmation" else None
    if frozen and (source_identity() != frozen["source"] or
                   any(digest(checkpoint(t)) != frozen["checkpoints"][t] for t in PROTOCOL["tasks"])):
        raise ValueError("Frozen source or checkpoint changed")
    identity = source_identity()
    write(out / "START_IDENTITY.json", dict(source=identity,
        checkpoint_sha256={t: digest(checkpoint(t)) for t in PROTOCOL["tasks"]},
        seed=PROTOCOL[phase + "_seed"], phase=phase, started_unix_ns=time.time_ns(),
        source_freeze_sha256=None if frozen is None else digest(HERE / "SOURCE_FREEZE.json")))
    rows, checks = [], []
    cpu_start, wall_start = time.process_time(), time.perf_counter()
    for task_index, task in enumerate(PROTOCOL["tasks"]):
        torch.manual_seed(PROTOCOL[phase + "_seed"])
        model = addressed_models.AddressedModel("flow").eval()
        model.load_state_dict(torch.load(checkpoint(task), weights_only=True, map_location="cpu"))
        for index, (batch_size, condition) in enumerate(PROTOCOL["workloads"]):
            arrays = data.batch(task, batch_size, PROTOCOL[phase + "_seed"], "dev", condition)
            check = numerical(model, arrays)
            check.update(task=task, batch=batch_size, condition=condition)
            checks.append(check)
            if condition == "base" and batch_size == 24:
                matrix_checks = independent_matrices(model, arrays)
                write(out / f"{task}_SCIPY.json", matrix_checks)
                checks.append(dict(task=task, matrix_checks=len(matrix_checks),
                                   passed=all(r["passed"] for r in matrix_checks)))
            for backward in (False, True):
                row = benchmark(model, arrays, backward, PROTOCOL[phase + "_seed"] + task_index * 100 + index)
                row.update(task=task, batch=batch_size, condition=condition, steps=arrays["x"].shape[1])
                rows.append(row)
                with (out / "TIMING_ROWS.jsonl").open("a") as stream:
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
            print(json.dumps(dict(task=task, batch=batch_size, condition=condition,
                                 numerical_pass=check["passed"],
                                 ratios=[r["dense_over_fused"] for r in rows[-2:]])), flush=True)
    result = dict(schema="hcsn.addressed-preparation.performance.v1", phase=phase,
        numerical_pass=all(r["passed"] for r in checks), checks=checks, results=rows,
        stable_complete_model_speed_gate=all(r["dense_over_fused"] >= 1.05 for r in rows),
        source_unchanged=source_identity() == identity, threads=torch.get_num_threads(),
        runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__, scipy=scipy.__version__),
        measured_body_cpu_seconds=time.process_time() - cpu_start,
        measured_body_wall_seconds=time.perf_counter() - wall_start,
        full_training_cost_measured=False, gpu=None, energy_joules=None,
        default_modified=False, production_activation=False,
        scope=PROTOCOL["scope"])
    write(out / "SUMMARY.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "development", "confirmation"))
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    if arguments.phase == "freeze":
        print(json.dumps(freeze(), indent=2))
    else:
        if arguments.out is None:
            parser.error("--out is required for a run")
        result = run(arguments.phase, arguments.out)
        print(json.dumps({k: result[k] for k in ("numerical_pass", "stable_complete_model_speed_gate", "source_unchanged")}, indent=2))
