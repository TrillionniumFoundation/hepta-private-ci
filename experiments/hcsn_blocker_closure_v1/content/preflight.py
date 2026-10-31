"""Train-only semantic, gradient, equivalence and resource preflight."""

import argparse
import math
from pathlib import Path
import resource
import sys
import time

import numpy as np
from scipy.linalg import expm
import torch
from torch.nn import functional as F

from experiments.hcsn_conservative_acceleration_v1.model import DistributionalClassifier
from experiments.hcsn_conservative_acceleration_v1.kernel import prepare_operator
from experiments.hcsn_distributional_v2.distribution_kernel import make_flow, Grid

from .data import generate
from .models import ARMS, PHYSICAL_ARMS, build, first_event_vectors
from .study import group_measurements, physical_audit, source_map, state_hash, write


def independent_first_event(parameters):
    """SciPy killed CTMC assembled independently from scalar finite-volume rates."""
    mu, sigma, boundary, reset, tau, rho, horizon = map(float, parameters)
    cells, phases, lower = 8, 2, -2.0
    size = cells + phases
    spacing = (boundary - lower) / cells
    centers = lower + (np.arange(cells) + .5) * spacing
    weights = np.maximum(0, 1 - np.abs(centers - reset) / spacing)
    weights /= weights.sum()
    diffusion = sigma * sigma / (2 * spacing * spacing)
    up = diffusion + max(mu, 0) / spacing
    down = diffusion + max(-mu, 0) / spacing
    exit_rate = 2 * diffusion + max(mu, 0) / spacing
    killed = np.zeros((size, size))
    for index in range(cells):
        if index > 0:
            killed[index, index - 1] = down
        if index < cells - 1:
            killed[index, index + 1] = up
        killed[index, index] = -killed[index].sum()
    killed[cells - 1, cells - 1] -= exit_rate
    phase_rate = phases / tau
    for phase in range(phases):
        row = cells + phase
        killed[row, row] = -phase_rate
        if phase < phases - 1:
            killed[row, row + 1] = phase_rate
        else:
            killed[row, :cells] = phase_rate * weights
    event = np.zeros(size)
    event[cells - 1] = exit_rate
    answers = []
    for discount in (0.0, rho):
        augmented = np.zeros((size + 1, size + 1))
        augmented[:size, :size] = killed - discount * np.eye(size)
        augmented[:size, size] = event
        answers.append(expm(augmented * horizon)[:size, size])
    return np.stack(answers)


def torch_first_event(parameters):
    mu, sigma, boundary, reset, tau, rho, horizon = parameters.unbind()
    grid = Grid(cells=8, lower=-2, refractory_stages=2, fixed_rate=8.1,
                fixed_terms=21, max_duration=.36, per_token_chunks=True)
    flow = make_flow(mu, sigma, boundary, reset, tau, grid)
    values = first_event_vectors(flow, rho, horizon)
    return torch.stack((values["F"], values["H"]))


def run(output):
    cpu, wall = time.process_time(), time.perf_counter()
    torch.set_num_threads(1)
    checks, details = [], {}

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))

    for task in ("selective_copy", "mqar"):
        arrays = generate(task, "dev_train", 8, 32, 77100231)
        reconstructed = np.full_like(arrays["y"], -100)
        for row, x in enumerate(arrays["x"]):
            memory, pending = {}, []
            for index, token in enumerate(x):
                if task == "selective_copy":
                    if token[8]:
                        pending.append(int(token[:8].argmax()))
                    if token[9]:
                        reconstructed[row, index] = pending.pop(0)
                else:
                    if token[16]:
                        memory[int(token[:8].argmax())] = int(token[8:16].argmax())
                    if token[17]:
                        reconstructed[row, index] = memory[int(token[:8].argmax())]
        check(task + ": label oracle from observed sequence", np.array_equal(reconstructed, arrays["y"]))

    parameters = torch.tensor([.17, .47, 1.31, -.073, .71, .43, .19], dtype=torch.float64, requires_grad=True)
    value = torch_first_event(parameters)
    oracle = independent_first_event(parameters.detach().numpy())
    check("first-event F/H independent SciPy", np.max(np.abs(value.detach().numpy() - oracle)) < 2e-12,
          float(np.max(np.abs(value.detach().numpy() - oracle))))
    jacobian = torch.autograd.functional.jacobian(torch_first_event, parameters).detach().numpy()
    finite = np.zeros_like(jacobian)
    for column in range(len(parameters)):
        plus, minus = parameters.detach().numpy().copy(), parameters.detach().numpy().copy()
        plus[column] += 1e-6
        minus[column] -= 1e-6
        finite[..., column] = (independent_first_event(plus) - independent_first_event(minus)) / 2e-6
    error = float(np.max(np.abs(jacobian - finite) / (1 + np.abs(finite))))
    check("first-event all seven parameter Jacobians versus independent finite differences", error < 2e-8, error)
    check("first-event discount and probability order", bool((value[1] >= 0).all()
          and (value[0] <= 1).all() and (value[1] <= value[0]).all()))
    zero = parameters.detach().clone()
    zero[-1] = 0
    check("first-event zero horizon", bool((torch_first_event(zero) == 0).all()))
    long = torch.tensor([.49, .5, .7, .01, .31, .4, 8.0], dtype=torch.float64)
    forecast = torch_first_event(long)
    grid = Grid(cells=8, lower=-2, refractory_stages=2, fixed_rate=8.1,
                fixed_terms=21, max_duration=.36, per_token_chunks=True)
    repeat = prepare_operator(*long[:5], long[-1], grid=grid)["event_vector"]
    check("repeat count differs from first-event probability", float(repeat[-3]) > 1
          and float(forecast[0, -3]) <= 1 + 2e-12,
          dict(repeat_C=float(repeat[-3]), first_F=float(forecast[0, -3]), discounted_H=float(forecast[1, -3])))

    tensors = {key: torch.from_numpy(value) for key, value in
               generate("selective_copy", "dev_train", 4, 16, 77100232).items()}
    reference = DistributionalClassifier(64, 8, seed=55317, backend="accelerated", profile="stable").double()
    wrapped = build("value_jg", seed=55317).double()
    check("JG wrapper identical initialization", state_hash(reference.state_dict()) == state_hash(wrapped.state_dict()))
    ref_logits = reference(tensors["x"].double(), tensors["dt"].double(), return_sequence=True, return_aux=False)
    new_logits = wrapped(tensors["x"].double(), tensors["dt"].double(), return_sequence=True, return_aux=False)
    check("JG wrapper forward equivalence", float((ref_logits - new_logits).abs().max().detach()) < 5e-13,
          float((ref_logits - new_logits).abs().max().detach()))
    ref_logits.square().mean().backward()
    new_logits.square().mean().backward()
    gradient_error = max(float((a.grad - b.grad).abs().max()) for a, b in zip(reference.parameters(), wrapped.parameters(), strict=True))
    check("JG wrapper gradient equivalence", gradient_error < 5e-12, gradient_error)
    del reference, wrapped, ref_logits, new_logits

    common_hashes, counts, timings = [], {}, {}
    for arm in ARMS:
        tick = time.process_time()
        model = build(arm, seed=55318)
        initial = {name: p.detach().clone() for name, p in model.named_parameters()}
        common_hashes.append(state_hash({key: value for key, value in model.state_dict().items()
                                        if key.startswith(("frontend.", "readout."))}))
        counts[arm] = model.counts()
        optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=.003)
        accumulated = {key: 0.0 for key in model.parameter_groups()}
        last_audit, last_features = {}, None
        for _ in range(2):
            optimizer.zero_grad(set_to_none=True)
            logits, aux = model(tensors["x"], tensors["dt"], return_sequence=True)
            selected = tensors["y"] >= 0
            loss = F.cross_entropy(logits[selected], tensors["y"][selected])
            loss.backward()
            gradients = group_measurements(model, initial, gradient=True)
            for group, row in gradients.items():
                accumulated[group] += row["l2"]
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2)
            optimizer.step()
            last_audit = physical_audit(aux)
            if arm in PHYSICAL_ARMS:
                last_features = aux["feature_coordinates"].detach()
        updates = group_measurements(model, initial)
        frozen = getattr(model, "frozen_group", None)
        check(arm + ": intended groups receive gradients and update", all(
            accumulated[group] == 0 and updates[group]["nonzero"] == 0 if group == frozen
            else accumulated[group] > 0 and updates[group]["nonzero"] > 0 for group in accumulated),
            dict(gradient_l2_sums=accumulated, updates=updates, frozen_group=frozen))
        if last_features is not None:
            variation = last_features.flatten(0, -3).std(0).amax(0)
            check(arm + ": all three feature coordinates active", bool((variation > 0).all()), variation.tolist())
        if arm.startswith(("fixed_", "learned_")):
            values = aux["boundary"].detach()
            check(arm + ": threshold independent of current observation", bool((values == values[0, :1]).all()))
        timings[arm] = dict(two_small_updates_cpu_seconds=time.process_time() - tick,
                           batch=4, length=16, final_train_loss=float(loss.detach()), physical=last_audit)
    check("all model frontend/readout initial tensors identical", len(set(common_hashes)) == 1)
    residents = [counts[arm]["backbone"] for arm in ARMS if not arm.startswith("freeze_")]
    spread = (max(residents) - min(residents)) / max(residents)
    check("active resident backbone spread <=3%", spread <= .03, spread)
    full_batch = {key: torch.from_numpy(value) for key, value in
                  generate("mqar", "dev_train", 32, 32, 77100233).items()}
    full_timings = {}
    for arm in ("value_jg", "value_fh", "transformer", "two_gates", "lif_snn", "mamba1"):
        model = build(arm, seed=55319)
        optimizer = torch.optim.Adam(model.parameters(), lr=.003)
        tick, start = time.process_time(), time.perf_counter()
        logits, aux = model(full_batch["x"], full_batch["dt"], return_sequence=True)
        selected = full_batch["y"] >= 0
        F.cross_entropy(logits[selected], full_batch["y"][selected]).backward()
        gradients_finite = all(bool(torch.isfinite(parameter.grad).all())
            for parameter in model.parameters() if parameter.grad is not None)
        gradient_nonzero = sum(int(torch.count_nonzero(parameter.grad))
            for parameter in model.parameters() if parameter.grad is not None)
        optimizer.step()
        audit = physical_audit(aux)
        full_timings[arm] = dict(one_full_update_cpu_seconds=time.process_time() - tick,
            wall_seconds=time.perf_counter() - start, batch=32, length=32, physical=audit,
            gradients_finite=gradients_finite, gradient_nonzero_coordinates=gradient_nonzero)
    check("all six full registered batch train-only gradients finite and nonzero", all(
        row["gradients_finite"] and row["gradient_nonzero_coordinates"] > 0 for row in full_timings.values()))
    details.update(counts=counts, train_only_timings=timings,
                   full_batch_train_only_timings=full_timings,
                   first_event_max_scaled_gradient_error=error,
                   first_event_state_domain="8 active cells and 2 remaining refractory phases")
    report = dict(schema="hcsn-blocker-content-preflight.v1", passed=all(row["passed"] for row in checks),
        checks=checks, details=details, source_sha256=source_map(),
        cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        data_scope="small new train-only probes; no development validation or formal heldout arrays",
        limitations=["A nonzero gradient does not prove task benefit", "Local Jacobian checks exclude interpolation knots", "No content-task optimality theorem"])
    write(output, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print({"passed": result["passed"], "checks": len(result["checks"]),
           "cpu_seconds": result["cpu_seconds"], "wall_seconds": result["wall_seconds"]}, flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
