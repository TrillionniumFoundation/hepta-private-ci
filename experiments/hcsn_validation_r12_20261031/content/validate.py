"""Independent NumPy parity, finite differences, causal-prefix and data checks."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from scipy.special import expit

from .data import dataset, twin_balance
from .models import FAMILIES, DualGate, Model, core_configs, renewal_gate
from .study import evaluate
from .upstream.content import Model as OriginalModel


def run():
    torch.set_num_threads(1)
    original = OriginalModel("analytic", 16, 16, 3, 123)
    a = torch.linspace(-8, 8, 17, dtype=torch.float64).repeat(5, 1).requires_grad_()
    dt = torch.tensor([0., .25, 1., 1.75, 4.], dtype=torch.float64)[:, None]
    gate = renewal_gate(a, dt)
    grad, = torch.autograd.grad(gate.sum(), a)
    reference, derivative = original.gate(a.detach().numpy(), dt.numpy(), derivative=True)
    gap, grad_gap = float(np.max(abs(reference-gate.detach().numpy()))), float(np.max(abs(derivative-grad.numpy())))
    assert gap < 2e-12 and grad_gap < 2e-11, (gap, grad_gap)
    core = DualGate("analytic", 17).double()
    rng = np.random.default_rng(12)
    x, h = rng.normal(size=(3, 16)), rng.normal(size=(3, 16))
    elapsed = np.array([[.25], [1.], [1.75]])
    p = {k: v.detach().numpy() for k, v in core.p.items()}
    candidate = np.tanh(x @ p["Wx"] + h @ p["Wh"] + p["Wb"])
    gate, _ = original.gate(x @ p["Gx"] + h @ p["Gh"] + p["Gb"], elapsed)
    write = expit(x @ p["Ix"] + h @ p["Ih"] + p["Ib"])
    expected = h + gate*(write*candidate-h)
    obtained = core.step(torch.tensor(x), torch.tensor(h), torch.tensor(elapsed))
    step_gap = float(np.max(abs(expected-obtained.detach().numpy())))
    assert step_gap < 2e-12
    # A whole recurrent loss derivative, not an implementation-shaped gradient test.
    sequence = torch.tensor(rng.normal(size=(2, 4, 16)), dtype=torch.float64)
    times = torch.ones((2, 4), dtype=torch.float64)
    loss = core(sequence, times).square().mean()
    loss.backward()
    parameter = core.p["Gx"]
    direction = torch.tensor(rng.normal(size=(16, 16)), dtype=torch.float64)
    direction /= direction.norm()
    analytical = float((parameter.grad*direction).sum())
    initial = parameter.detach().clone()
    with torch.no_grad():
        parameter.copy_(initial+1e-5*direction); plus = float(core(sequence, times).square().mean())
        parameter.copy_(initial-1e-5*direction); minus = float(core(sequence, times).square().mean())
        parameter.copy_(initial)
    finite_difference = (plus-minus)/2e-5
    assert abs(analytical-finite_difference) < 1e-8
    configs = core_configs()
    prefix_errors, parameter_counts = {}, {}
    values = dataset("recall", "val")
    inputs = torch.from_numpy(values["x"][:2])
    times = torch.from_numpy(values["dt"][:2])
    for family in FAMILIES:
        model = Model("recall", family, 5, configs[family])
        with torch.no_grad():
            _, states = model(inputs, times, True)
            changed = inputs.clone(); changed[:, 5:] = torch.randn_like(changed[:, 5:])
            _, other = model(changed, times, True)
        error = float((states[:, :5]-other[:, :5]).abs().max())
        assert error < 2e-6, (family, error)
        prefix_errors[family] = error
        parameter_counts[family] = sum(p.numel() for p in model.core.parameters())
        evaluate(model, values, 64)
    for domain in ("missing_a", "missing_b"):
        assert twin_balance(dataset("binding", "val", domain)), domain
    return dict(passed=True, renewal_probability_max_gap=gap, renewal_gradient_max_gap=grad_gap,
                dual_step_max_gap=step_gap, recurrent_directional_AD=analytical,
                recurrent_directional_finite_difference=finite_difference,
                causal_prefix_errors=prefix_errors, core_parameter_counts=parameter_counts,
                exact_single_modality_label_balance=True, test_split_opened=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2); stream.write("\n")
    print(json.dumps(result))
