"""MP80 block-exponential reference for noncommuting first/second derivatives."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import mpmath as mp
import numpy as np
import torch

ROOT = Path(__file__).resolve().parent
mp.mp.dps = 80
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
spec = importlib.util.spec_from_file_location("review_kernel", ROOT / "kernel_snapshot.py")
kernel = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = kernel
spec.loader.exec_module(kernel)


def mp_matrix(array):
    return mp.matrix([[mp.mpf(float(value)) for value in row] for row in array])


def block_action(a, directions):
    n, count = a.rows, 1 + len(directions)
    block = mp.zeros(n * count)
    for level in range(count):
        for i in range(n):
            for j in range(n):
                block[level * n + i, level * n + j] = a[i, j]
                if level < len(directions):
                    block[level * n + i, (level + 1) * n + j] = directions[level][i, j]
    result = mp.expm(block)
    return mp.matrix([[result[i, (count - 1) * n + j] for j in range(n)] for i in range(n)])


def main():
    plan = json.loads((ROOT / "PLAN.json").read_text())
    before = hashlib.sha256((ROOT / "kernel_snapshot.py").read_bytes()).hexdigest()
    if before != plan["kernel_sha256"]:
        raise ValueError("frozen source mismatch")
    started = time.perf_counter()
    raw = np.array([[-.3, .7, -.2], [.05, -.1, .2], [.4, .08, -.6]], dtype=np.float64)
    b = np.array([[.2, -.4, .3], [.1, .1, 0.], [-.2, .25, .05]]) * .2
    c = np.array([[-.1, .2, .05], [0., .3, -.2], [.15, -.05, .2]]) * .25
    w = np.linspace(-.4, .8, 9).reshape(3, 3)
    mb, mc, mw = map(mp_matrix, (b, c, w))

    def contract(matrix):
        return sum(mw[i, j] * matrix[i, j] for i in range(3) for j in range(3))

    rows = []
    for norm in plan["norm_roster"]:
        a = raw * (norm / np.linalg.norm(raw, 1))
        theta = torch.zeros(2, dtype=torch.float64, requires_grad=True)
        matrix = torch.from_numpy(a) + theta[0] * torch.from_numpy(b) + theta[1] * torch.from_numpy(c)
        work = kernel.Work()
        actual = work.exponential(matrix)
        loss = (actual * torch.from_numpy(w)).sum()
        grad, = torch.autograd.grad(loss, (theta,), create_graph=True)
        hessian = torch.stack([torch.autograd.grad(grad[i], (theta,), retain_graph=True)[0] for i in range(2)])
        ma = mp_matrix(a)
        value = mp.expm(ma)
        exact_gradient = [contract(block_action(ma, [direction])) for direction in (mb, mc)]
        exact_hessian = [[contract(2 * block_action(ma, [mb, mb])),
                          contract(block_action(ma, [mb, mc]) + block_action(ma, [mc, mb]))],
                         [None, contract(2 * block_action(ma, [mc, mc]))]]
        exact_hessian[1][0] = exact_hessian[0][1]
        reference = torch.tensor([[float(value[i, j]) for j in range(3)] for i in range(3)], dtype=torch.float64)
        reference_gradient = torch.tensor([float(v) for v in exact_gradient], dtype=torch.float64)
        reference_hessian = torch.tensor([[float(v) for v in row] for row in exact_hessian], dtype=torch.float64)
        for name, measured, expected in (("value", actual, reference), ("gradient", grad, reference_gradient),
                                         ("hessian", hessian, reference_hessian)):
            if not bool(torch.isfinite(measured).all()):
                raise FloatingPointError("nonfinite " + name)
            torch.testing.assert_close(measured, expected, **plan["tolerances"][name])
        rows.append({"declared_norm": norm, "actual_norm_1": float(np.linalg.norm(a, 1)),
                     "small_norm_actions": work.small_norm_exponentials,
                     "native_actions": work.native_exponentials,
                     "input": a.tolist(), "direction_b": b.tolist(), "direction_c": c.tolist(), "weights": w.tolist(),
                     "commutator_ab_norm_1": float(np.linalg.norm(a @ b - b @ a, 1)),
                     "commutator_ac_norm_1": float(np.linalg.norm(a @ c - c @ a, 1)),
                     "commutator_bc_norm_1": float(np.linalg.norm(b @ c - c @ b, 1)),
                     "actual": actual.detach().tolist(), "reference_mp80": [[str(value[i, j]) for j in range(3)] for i in range(3)],
                     "gradient": grad.detach().tolist(), "gradient_reference_mp80": [str(v) for v in exact_gradient],
                     "hessian": hessian.detach().tolist(), "hessian_reference_mp80": [[str(v) for v in row] for row in exact_hessian],
                     "value_max_abs_error": float((actual.detach() - reference).abs().max()),
                     "gradient_max_abs_error": float((grad.detach() - reference_gradient).abs().max()),
                     "hessian_max_abs_error": float((hessian.detach() - reference_hessian).abs().max())})
    if hashlib.sha256((ROOT / "kernel_snapshot.py").read_bytes()).hexdigest() != before:
        raise ValueError("source changed during review")
    result = {"schema": "hcsn-small-norm-independent-frechet-review-v1", "rows": rows,
              "kernel_sha256": before, "all_declared_checks_pass": True,
              "reference": "MP80 exact binary64 inputs; 3x3 values, 6x6 and 9x9 block exponentials",
              "model_calls": 0, "optimizer_calls": 0, "dataset_rows": 0, "mp_exponential_calls": 28,
              "body_wall_seconds": time.perf_counter() - started,
              "scope": "Values and branch AD/Hessians at four declared matrices, not global floating-point certification"}
    (ROOT / "attempt001" / "RESULT.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"all_pass": True, "cases": len(rows), "max_value": max(r["value_max_abs_error"] for r in rows),
                      "max_gradient": max(r["gradient_max_abs_error"] for r in rows),
                      "max_hessian": max(r["hessian_max_abs_error"] for r in rows)}))


if __name__ == "__main__":
    main()
