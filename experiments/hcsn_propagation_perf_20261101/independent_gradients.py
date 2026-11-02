"""Physical-parameter Jacobian check against independent SciPy differences.

This is supplementary engineering verification, not a selected task outcome.
It uses independent NumPy jump assembly; no PyTorch reference gradient is used.
"""

import json
from pathlib import Path

import numpy as np
from scipy.linalg import expm
import torch

from experiments.hcsn_addressed_flow_20261101 import addressed_models, data
from experiments.hcsn_four_stage_flow_20261031.operator_audit import independent_generator
from . import audit, fused_addressed


def reference(physical, duration, weights):
    sigmoid = lambda x: 1 / (1 + np.exp(-x))
    sigma, tau = .15 + .4 * sigmoid(physical[0]), .15 + .7 * sigmoid(physical[1])
    eta, decay = sigmoid(physical[3]), .05 * sigmoid(physical[4])
    # Interval zero precedes every observation, so its policy controls are zero.
    case = dict(parameters=[.05 + .9 * sigmoid(physical[2]), sigma, 1., -.5, tau],
                cells=4, phases=1, lower=-1.5)
    q, mark, _, _ = independent_generator(case)
    return float(np.sum(expm(q * duration) * weights[0])
                 + np.sum(expm((q - (1 - eta) * mark - decay * np.eye(5)) * duration) * weights[1]))


def run():
    torch.set_num_threads(1)
    rows = []
    rng = np.random.default_rng(971491)
    for task in ("mqar", "binding"):
        torch.manual_seed(971491)
        model = addressed_models.AddressedModel("flow").eval()
        model.load_state_dict(torch.load(audit.checkpoint(task), weights_only=True, map_location="cpu"))
        arrays = data.batch(task, 3, 971491, "dev", "missing")
        x, dt, seen = [torch.from_numpy(arrays[k]) for k in ("x", "dt", "observed")]
        weights = rng.normal(size=(2, 5, 5)).astype(np.float32)
        prepared = fused_addressed.prepare(model, model.encode(x), dt, seen)
        loss = sum((prepared[key][0, 0] * torch.tensor(weights[i], dtype=torch.float32)).sum()
                   for i, key in enumerate(("P", "T")))
        actual = torch.autograd.grad(loss, model.physical)[0].detach().double().numpy()
        physical = model.physical.detach().double().numpy()
        for parameter in range(5):
            step = 1e-5
            plus, minus = physical.copy(), physical.copy()
            plus[parameter] += step
            minus[parameter] -= step
            expected = (reference(plus, float(dt[0, 0]), weights)
                        - reference(minus, float(dt[0, 0]), weights)) / (2 * step)
            error = float(abs(actual[parameter] - expected))
            rows.append(dict(task=task, parameter=parameter, scipy_central_difference=float(expected),
                             autograd=float(actual[parameter]), absolute_error=error,
                             step=step, tolerance=2e-5, passed=error <= 2e-5))
    result = dict(schema="hcsn.addressed-preparation.physical-gradient.v1", rows=rows,
                  passed=all(r["passed"] for r in rows),
                  source_sha256={str(p.relative_to(audit.ROOT)): audit.digest(p) for p in
                                 [Path(__file__), Path(fused_addressed.__file__),
                                  audit.ROOT / "experiments/hcsn_four_stage_flow_20261031/operator_audit.py"]},
                  scope="Physical parameters at initial-policy interval; not a uniform gradient bound")
    audit.write(audit.HERE / "INDEPENDENT_GRADIENTS.json", result)
    print(json.dumps(dict(passed=result["passed"], checks=len(rows),
                          max_absolute_error=max(r["absolute_error"] for r in rows))))


if __name__ == "__main__":
    run()
