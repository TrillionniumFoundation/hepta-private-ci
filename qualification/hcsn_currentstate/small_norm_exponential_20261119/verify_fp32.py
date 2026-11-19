"""Run the fixed regression roster and quantify the original T=.61 failure."""

from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import unittest

import torch

from qualification.hcsn_currentstate.differentiable import Physics, Work, advance, initial, refractory


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
torch.set_num_threads(1)
torch.set_num_interop_threads(1)


def main(output):
    started = time.perf_counter()
    request = json.loads((HERE / "REQUEST_FP32.json").read_text())
    for name, digest in request["source_sha256"].items():
        if hashlib.sha256((REPO / name).read_bytes()).hexdigest() != digest:
            raise ValueError("source changed: " + name)
    suite = unittest.defaultTestLoader.loadTestsFromNames(request["test_modules"])
    if suite.countTestCases() != request["expected_test_cases"]:
        raise ValueError("frozen test roster changed")
    tests = unittest.TextTestRunner(verbosity=2).run(suite)
    if not tests.wasSuccessful():
        raise AssertionError("strict regression failed")
    rate = torch.tensor(1.7, dtype=torch.float64, requires_grad=True)
    alpha = torch.tensor([[1.], [-.4], [.3]], dtype=torch.float64, requires_grad=True)
    z = rate.new_zeros(())
    physics = Physics(-rate.reshape(1, 1), rate[None], z[None], rate.new_ones(1), z[None], z, z, z, F(1, 5))
    work = Work()
    state = advance(initial(alpha), physics, F(61, 100), work)
    observed = torch.cat((state.active[:, 0], state.hits, refractory(state, work)))

    def hits(time):
        total = rate.new_zeros(())
        for order in range(1, 5):
            remaining = time - (order-1)*.2
            if remaining > 0:
                x = rate*remaining
                total = total + 1 - torch.exp(-x)*sum(x**j/math.factorial(j) for j in range(order))
        return total

    count = hits(.61)
    waiting = count-hits(.41)
    expected = torch.cat(tuple(alpha[:, 0]*v for v in (1-waiting, count, waiting)))
    weights = torch.linspace(-.7, 1.2, observed.numel(), dtype=torch.float64)
    observed_g = torch.autograd.grad(observed @ weights, (rate, alpha), create_graph=True)
    expected_g = torch.autograd.grad(expected @ weights, (rate, alpha), create_graph=True)
    observed_h, = torch.autograd.grad(observed_g[0], (rate,))
    expected_h, = torch.autograd.grad(expected_g[0], (rate,))
    fp32 = torch.diag(torch.tensor([-.5, -.25], dtype=torch.float32))
    fp32_expected = torch.diag(torch.exp(torch.diag(fp32)))
    fp32_work = Work()
    fp32_fixed = fp32_work.exponential(fp32)
    fp32_native = torch.matrix_exp(fp32)
    report = {"fp32_diagonal_counterexample": {"norm1": .5,
              "native_max_abs_error": float((fp32_native-fp32_expected).abs().max()),
              "fixed_max_abs_error": float((fp32_fixed-fp32_expected).abs().max()),
              "fixed_values": fp32_fixed.tolist(), "native_values": fp32_native.tolist(),
              "reference_values": fp32_expected.tolist()},
              "tests_run": tests.testsRun, "all_passed": True,
              "original_strict_limits": {"atol": 3e-13, "rtol": 3e-12},
              "gamma61_max_abs_value_error": float((observed-expected).detach().abs().max()),
              "gamma61_rate_gradient_error": float((observed_g[0]-expected_g[0]).detach().abs()),
              "gamma61_content_gradient_error": float((observed_g[1]-expected_g[1]).detach().abs().max()),
              "gamma61_rate_second_derivative_error": float((observed_h-expected_h).detach().abs()),
              "observed": observed.detach().tolist(), "analytic": expected.detach().tolist(),
              "gamma61_work": {"logical_exponentials": work.exponentials,
                               "small_norm_horner": work.small_norm_exponentials,
                               "native_matrix_exp": work.native_exponentials},
              "optimizer_calls": 0, "training_grids_rerun": 0,
              "body_wall_seconds": time.perf_counter()-started}
    (output / "RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
