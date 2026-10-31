"""Independent central differences and literal official CfC equation check."""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import expit
from models import Model, gate


def main():
    rng = np.random.default_rng(18471)
    x = rng.normal(0, 0.3, (3, 5, 7))
    dt = rng.uniform(0.04, 0.14, (3, 5))
    y = np.array([0, 3, 5])
    records = []
    for kind in ("ordinary", "matched_c1", "analytic", "cfc"):
        model = Model(kind, 4, input_dim=7, seed=103101)
        _, grad = model.loss(x, dt, y)
        for trial in range(8):
            direction = {key: rng.normal(size=value.shape) for key, value in model.p.items()}
            norm = np.sqrt(sum(np.sum(v * v) for v in direction.values()))
            direction = {key: value / norm for key, value in direction.items()}
            expected = sum(np.sum(grad[k] * direction[k]) for k in direction)
            epsilon = 1e-5
            saved = {k: v.copy() for k, v in model.p.items()}
            for k in model.p:
                model.p[k] = saved[k] + epsilon * direction[k]
            plus = model.loss(x, dt, y, gradients=False)
            for k in model.p:
                model.p[k] = saved[k] - epsilon * direction[k]
            minus = model.loss(x, dt, y, gradients=False)
            model.p = saved
            numerical = (plus - minus) / (2 * epsilon)
            error = abs(expected - numerical)
            relative = error / max(abs(expected), abs(numerical), 1e-8)
            records.append(dict(kind=kind, trial=trial, exact=float(expected), numerical=float(numerical),
                                absolute_error=float(error), relative_error=float(relative)))
            assert error < 2e-8 or relative < 2e-5
    cfc = Model("cfc", 4, input_dim=7, seed=789)
    manual = np.zeros((len(x), 4))
    for t in range(x.shape[1]):
        q = np.concatenate((x[:, t], manual), axis=1)
        ff1 = np.tanh(q @ cfc.p["w"][:, :4] + cfc.p["b"][:4])
        ff2 = np.tanh(q @ cfc.p["w"][:, 4:8] + cfc.p["b"][4:8])
        time_a = q @ cfc.p["w"][:, 8:12] + cfc.p["b"][8:12]
        time_b = q @ cfc.p["w"][:, 12:] + cfc.p["b"][12:]
        mix = expit(time_a * dt[:, t, None] + time_b)
        manual = ff1 * (1 - mix) + mix * ff2
    actual = cfc.forward(x, dt)[1]
    assert np.allclose(actual, manual, rtol=2e-14, atol=2e-14)
    zeros = np.zeros((5, 4))
    times = np.linspace(0.04, 0.16, 5)[:, None]
    ap, ag = gate("analytic", zeros, times)
    mp, mg = gate("matched_c1", zeros, times)
    assert np.allclose(ap, mp, rtol=2e-14, atol=2e-14)
    assert np.allclose(ag, mg, rtol=2e-14, atol=2e-14)
    root = Path(__file__).resolve().parent
    receipt = dict(passed=True, directional_checks=records,
                   cfc_literal_equation_max_abs=float(np.max(np.abs(actual - manual))),
                   matched_value_max_abs=float(np.max(np.abs(ap - mp))),
                   matched_slope_max_abs=float(np.max(np.abs(ag - mg))),
                   source_sha256=hashlib.sha256((root / "models.py").read_bytes()).hexdigest(),
                   torch_execution=False,
                   scope="NumPy gradients and exact default equation; no official PyTorch runtime installed")
    (root / "GRADIENT_CHECK.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(records), "maximum_error": max(r["absolute_error"] for r in records)}))


if __name__ == "__main__":
    main()
