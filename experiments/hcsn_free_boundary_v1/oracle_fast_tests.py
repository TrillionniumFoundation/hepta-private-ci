"""Independent accuracy, certificate, gradient and CPU probes for oracle_fast.

Runs only synthetic scalar parameters and freshly initialized synthetic-input
models. No frozen-study checkpoint, prediction or outcome is read.
"""

import argparse
from contextlib import nullcontext
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import unittest

import mpmath as mp
import numpy as np
from scipy.optimize import brentq
from scipy.special import lambertw
import torch
from torch.nn import functional as F

from . import model as model_module
from .model import HCSNClassifier
from .oracle_fast import (EPS, dimensionless_root, free_boundary,
                          model_runtime_adapter, rational_certificate)
from .oracle_torch import free_boundary as old_boundary


PACKAGE = Path(__file__).resolve().parent


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _mp_root(a):
    return mp.re(1 + mp.lambertw(-mp.exp(-1 - a), 0))


def _mp_boundary(*values):
    mu, sigma, rho, K, reset, tau = values
    omega = mp.sqrt(mu * mu + 2 * rho * sigma * sigma)
    kap = 2 * rho / (omega + mu) if mu >= 0 else (omega - mu) / (sigma * sigma)
    return K + _mp_root(rho * tau + kap * (K - reset)) / kap


def _scalar_residual(y, a):
    z = a + y
    if z < 0.125:
        return math.fsum([(-1) ** n * z**n / math.factorial(n) for n in range(2, 15)]) - a
    return y + math.expm1(-z)


def accuracy_grid():
    values = np.logspace(-16, 8, 481)
    a = torch.from_numpy(values)
    y, diagnostics = dimensionless_root(a, True)
    scalar = torch.tensor(0.0, dtype=torch.float64)
    old = old_boundary(scalar + 0.5, scalar + 1, scalar + 1, scalar, -a, scalar).detach().numpy()
    records = []
    with mp.workdps(100):
        for index, (av, result, previous) in enumerate(zip(values, y.tolist(), old.tolist(), strict=True)):
            reference = _mp_root(mp.mpf(float(av)))
            relative = float(abs(mp.mpf(result) - reference) / reference)
            old_relative = float(abs(mp.mpf(previous) - reference) / reference)
            certificate = rational_certificate(av, result)
            assert certificate["certified"]
            assert mp.mpf(certificate["lower"]) <= reference <= mp.mpf(certificate["upper"])
            assert abs(mp.mpf(result) - reference) <= mp.mpf(certificate["root_absolute_error_bound"])
            independent = brentq(_scalar_residual, 0, 1, args=(float(av),),
                                 xtol=np.nextafter(0.0, 1.0), rtol=4 * np.finfo(float).eps)
            scipy_relative = float(abs(mp.mpf(independent) - reference) / reference)
            # Direct double Lambert-W is only a diagnostic, never the small-a oracle.
            direct = lambertw(-np.exp(-1 - av), 0)
            direct_value = float(1 + direct.real) if np.isfinite(direct.real) and abs(direct.imag) < 1e-12 else None
            records.append(dict(a=float(av), y=result, high_precision_reference=str(reference),
                                relative_error=relative, frozen32_relative_error=old_relative,
                                scipy_brent_relative_error=scipy_relative,
                                scipy_direct_lambert_y=direct_value,
                                certificate=certificate,
                                relative_condition=float(diagnostics["relative_condition_number"][index]),
                                absolute_dy_da=float(diagnostics["dy_da"][index])))
    maximum = max(r["relative_error"] for r in records)
    assert maximum < 5e-15
    assert max(r["certificate"]["root_relative_error_bound"] for r in records) < 2e-14
    return dict(points=len(records), log10_a_range=[-16, 8], maximum_relative_error=maximum,
                maximum_frozen32_relative_error=max(r["frozen32_relative_error"] for r in records),
                maximum_scipy_brent_relative_error=max(r["scipy_brent_relative_error"] for r in records),
                fallback_elements=diagnostics["fallback_elements"],
                fallback_iterations=diagnostics["fallback_iterations"], records=records)


def gradient_audit():
    cases = [(.25, .7, .4, .8, -.2, .3), (-.7, .4, .8, 1.1, -.5, .6),
             (1.5, .2, .06, .3, .1, .01), (.5, 1, 1, 0, -1e-16, 0),
             (0, 1, .4, 0, -1e-12, 1e-13), (.5, 1, 1, .8, -.2, 1000)]
    records = []
    with mp.workdps(100):
        for values in cases:
            arguments = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in values)
            result = free_boundary(*arguments)
            actual = torch.autograd.grad(result, arguments)
            previous = old_boundary(*arguments)
            old_derivatives = torch.autograd.grad(previous, arguments)
            exact = tuple(mp.mpf(v) for v in values)
            reference = _mp_boundary(*exact)
            derivatives = []
            for i, (computed, older) in enumerate(zip(actual, old_derivatives, strict=True)):
                def target(value):
                    modified = list(exact)
                    modified[i] = value
                    return _mp_boundary(*modified)
                expected = mp.diff(target, exact[i])
                absolute = float(abs(mp.mpf(computed.item()) - expected))
                relative = float(abs((mp.mpf(computed.item()) - expected) / expected)) if expected else None
                old_relative = float(abs((mp.mpf(older.item()) - expected) / expected)) if expected else None
                assert absolute <= 3e-13 * max(1, abs(float(expected)))
                derivatives.append(dict(parameter=("mu", "sigma", "rho", "K", "r", "tau")[i],
                                        value=computed.item(), reference=str(expected),
                                        absolute_error=absolute, relative_error=relative,
                                        frozen32_relative_error=old_relative))
            assert abs(result.item() - float(reference)) <= 3e-14 * max(1, abs(float(reference)))
            records.append(dict(parameters=values, boundary=result.item(), reference=str(reference),
                                gradients=derivatives))
    checks = []
    for values in cases[:3]:
        arguments = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in values)
        checks.append(bool(torch.autograd.gradcheck(free_boundary, arguments, eps=1e-6, atol=3e-6, rtol=2e-4)))
    broadcast = (torch.tensor([[-.3], [.2], [.8]], dtype=torch.float64, requires_grad=True),
                 torch.tensor([[.4, .9]], dtype=torch.float64, requires_grad=True),
                 torch.tensor(.4, dtype=torch.float64, requires_grad=True),
                 torch.tensor(.8, dtype=torch.float64, requires_grad=True),
                 torch.tensor(-.2, dtype=torch.float64, requires_grad=True),
                 torch.tensor([[.1, .4]], dtype=torch.float64, requires_grad=True))
    checks.append(bool(torch.autograd.gradcheck(free_boundary, broadcast, eps=1e-6, atol=3e-6, rtol=2e-4)))
    assert all(checks)
    return dict(physical_cases=records, scalar_gradchecks=checks[:3], broadcast_gradcheck=checks[-1],
                scope="first derivatives only; near-branch derivatives checked against 100-digit reference, not large-step finite differences")


def _timed(function, repetitions):
    started = time.process_time()
    for _ in range(repetitions):
        function()
    return (time.process_time() - started) / repetitions


def paired_cpu_times(original, replacement, repetitions, blocks=7):
    for _ in range(2):
        original()
        replacement()
    pairs = []
    for block in range(blocks):
        if block % 2:
            newer = _timed(replacement, repetitions)
            older = _timed(original, repetitions)
        else:
            older = _timed(original, repetitions)
            newer = _timed(replacement, repetitions)
        pairs.append(dict(original_cpu_seconds=older, fast_cpu_seconds=newer, ratio=older / newer))
    ratios = [p["ratio"] for p in pairs]
    return dict(blocks=blocks, repetitions_per_block=repetitions, pairs=pairs,
                original_cpu_seconds_median=float(np.median([p["original_cpu_seconds"] for p in pairs])),
                fast_cpu_seconds_median=float(np.median([p["fast_cpu_seconds"] for p in pairs])),
                paired_speedup_median=float(np.median(ratios)),
                paired_speedup_range=[min(ratios), max(ratios)],
                interpretation="single-thread interleaved CPU timing replicates, not independent training seeds or accuracy evidence")


def boundary_benchmark():
    records = []
    for shape, repetitions in (((), 12), ((32,), 12), ((8, 32, 32), 4), ((32, 32, 32), 3)):
        size = math.prod(shape)
        mu = torch.linspace(-.25, .65, size, dtype=torch.float32).reshape(shape).requires_grad_()
        arguments = (mu,) + tuple(torch.full(shape, v, dtype=torch.float32, requires_grad=True)
                                  for v in (.65, .4, .8, -.2, .3))
        for backward in (False, True):
            def execute(solver):
                if backward:
                    for argument in arguments:
                        argument.grad = None
                    solver(*arguments).sum().backward()
                else:
                    with torch.no_grad():
                        solver(*arguments)
            timing = paired_cpu_times(lambda: execute(old_boundary), lambda: execute(free_boundary), repetitions)
            records.append(dict(shape=list(shape), dtype="float32", backward=backward, **timing))
    return records


def model_probe():
    records = []
    original_symbol = model_module.free_boundary
    for batch in (8, 32):
        model = HCSNClassifier(64, 10, width=32, depth=1, seed=7801)
        generator = torch.Generator().manual_seed(7802)
        x = torch.randn(batch, 32, 64, generator=generator)
        dt = torch.full((batch, 32), .2)
        labels = torch.randint(0, 10, (batch, 32), generator=generator)
        def execute(fast, backward, return_values=False):
            with model_runtime_adapter() if fast else nullcontext():
                if backward:
                    model.zero_grad(set_to_none=True)
                    output = model(x, dt, return_sequence=True, return_aux=False)
                    F.cross_entropy(output.flatten(0, 1), labels.flatten()).backward()
                    if return_values:
                        return output.detach().clone(), torch.cat([p.grad.flatten() for p in model.parameters()])
                else:
                    with torch.no_grad():
                        output = model(x, dt, return_sequence=True, return_aux=False)
                    if return_values:
                        return output
        output_old, grad_old = execute(False, True, True)
        output_new, grad_new = execute(True, True, True)
        error = dict(maximum_output_absolute_error=float((output_old - output_new).abs().max()),
                     maximum_gradient_absolute_error=float((grad_old - grad_new).abs().max()),
                     relative_gradient_l2_error=float((grad_old - grad_new).norm() / grad_old.norm()))
        assert error["maximum_output_absolute_error"] < 2e-6
        assert error["relative_gradient_l2_error"] < 2e-6
        for backward in (False, True):
            timing = paired_cpu_times(lambda: execute(False, backward), lambda: execute(True, backward), 1)
            records.append(dict(batch=batch, length=32, width=32, depth=1, input_dim=64, classes=10,
                                backward=backward, optimizer_update=False, **error, **timing))
        assert model_module.free_boundary is original_symbol
    return dict(synthetic_inputs_only=True, seed=7801, probe_records=records,
                frozen_main_model_source_changed=False, main_training_budget_changed=False,
                quality_or_generalization_improvement_tested=False,
                conditional_amdahl=dict(parent_reported_root_training_fraction=.12,
                                        ideal_infinite_root_speedup_limit=1 / (1 - .12),
                                        formula="overall <= 1/(1-f+f/root_speedup), if all other costs are unchanged",
                                        scope="conditional on the separately reported f=0.12 profile; different workload/noise can change f"))


class FastSolverTests(unittest.TestCase):
    def test_small_large_and_endpoint(self):
        a = torch.tensor([1e-16, 1e-8, .01, 1, 40, 1e8], dtype=torch.float64)
        y, diagnostics = dimensionless_root(a, True)
        self.assertTrue(bool(((y > 0) & (y <= 1)).all()))
        self.assertEqual(y[-1].item(), 1.0)
        self.assertEqual(diagnostics["fallback_elements"], 0)
        with mp.workdps(80):
            for av, yv in zip(a.tolist(), y.tolist(), strict=True):
                self.assertLess(float(abs(mp.mpf(yv) - _mp_root(mp.mpf(av))) / _mp_root(mp.mpf(av))), 5e-15)

    def test_forced_fallback_and_failure(self):
        a = torch.tensor([1e-16, .01, .4, 10], dtype=torch.float64)
        y, diagnostics = dimensionless_root(a, True, fast_steps=0)
        self.assertGreater(diagnostics["fallback_elements"], 0)
        self.assertTrue(bool(diagnostics["converged"].all()))
        self.assertTrue(torch.allclose(y, dimensionless_root(a), rtol=5e-15, atol=0))
        with self.assertRaises(RuntimeError):
            dimensionless_root(a, fast_steps=0, max_fallback_steps=0)

    def test_exact_certificate_rejects_wrong_root(self):
        y = dimensionless_root(torch.tensor(.3, dtype=torch.float64)).item()
        self.assertTrue(rational_certificate(.3, y)["certified"])
        with self.assertRaises(RuntimeError):
            rational_certificate(.3, y + .001, max_expansions=2)

    def test_bad_domain(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                dimensionless_root(torch.tensor(value, dtype=torch.float64))
        with self.assertRaises(TypeError):
            dimensionless_root(torch.tensor(1))

    def test_adapter_restores_after_exception(self):
        original = model_module.free_boundary
        with self.assertRaises(RuntimeError):
            with model_runtime_adapter():
                self.assertIs(model_module.free_boundary, free_boundary)
                raise RuntimeError("deliberate probe abort")
        self.assertIs(model_module.free_boundary, original)


def run(output, benchmark=True):
    torch.set_num_threads(1)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Use a fresh evidence directory; previous fast-solver evidence is immutable")
    started_cpu, started = time.process_time(), time.perf_counter()
    protected = {name: _hash(PACKAGE / name) for name in ("oracle.py", "oracle_torch.py", "model.py", "PROTOCOL.json")}
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FastSolverTests)
    tests = unittest.TextTestRunner(verbosity=2).run(suite)
    if not tests.wasSuccessful():
        raise RuntimeError("Fast solver unit tests failed")
    grid = accuracy_grid()
    gradients = gradient_audit()
    boundary_times = boundary_benchmark() if benchmark else []
    model_times = model_probe() if benchmark else None
    after = {name: _hash(PACKAGE / name) for name in protected}
    assert protected == after
    report = dict(schema="hcsn.fast-solver-extension.v1", status="passed", unit_tests=tests.testsRun,
                  grid=grid, gradients=gradients, boundary_benchmarks=boundary_times, model_probe=model_times,
                  first_order_only=True, frozen_study_used=False, frozen_sources_unchanged=True,
                  protected_source_sha256=protected,
                  source_sha256={name: _hash(PACKAGE / name) for name in ("oracle_fast.py", "oracle_fast_tests.py")},
                  environment=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__,
                                   mpmath=mp.__version__, torch_threads=torch.get_num_threads(), device="CPU"),
                  cpu_seconds=time.process_time() - started_cpu, wall_seconds=time.perf_counter() - started,
                  cost_scope="validation/probes after imports; main training, outcomes and budgets untouched",
                  certificate_timing_scope="exact-rational certificates excluded from fast-path speed benchmarks")
    output.mkdir(parents=True, exist_ok=True)
    (output / "RESULTS.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PACKAGE / "results/fast_solver001")
    parser.add_argument("--no-benchmark", action="store_true")
    args = parser.parse_args()
    report = run(args.output, not args.no_benchmark)
    print(json.dumps(dict(status=report["status"], grid_points=report["grid"]["points"],
                          maximum_relative_error=report["grid"]["maximum_relative_error"],
                          cpu_seconds=report["cpu_seconds"])))


if __name__ == "__main__":
    main()
