"""Independent mathematical checks of the memory-saving risk-vector profile."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

import numpy as np
from scipy.linalg import expm
import torch

from experiments.hcsn_distributional_v2.distribution_kernel import Grid, make_flow
from experiments.hcsn_distributional_v2.kernel_tests import independent_generator
from experiments.hcsn_distributional_v2.risk_independent_audit import independent_survival_remap
from experiments.hcsn_risk_ablation_v1 import risk_kernel as oracle
from .vector_kernel import PROFILE, MAX_DIRECT_CHUNKS, backward_jump, first_event_vector, first_event_probability


DURATIONS = [0., .12, .36, .360001, .495755147934, .72, .720001, 1.079999,
             3.2, 5.76, 5.760001, 7.31, 100.]
LIMITS = dict(vector_oracle_absolute=3e-12, dense_extra_roundoff=3e-12,
              backward_operator_absolute=3e-14,
              gradient_oracle_absolute=2e-12, gradient_oracle_relative=2e-9,
              independent_fd_scaled=3e-6, independent_fd_step=1e-5)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grid(phases):
    return Grid(8, -2., phases, fixed_rate=8.1, fixed_terms=21, max_duration=.36, per_token_chunks=True)


def dense(parameters, current_grid, old, duration):
    full, event, _, reset = independent_generator(*parameters, current_grid)
    destination = np.zeros(len(full))
    if current_grid.refractory_stages:
        destination[8] = 1
    else:
        destination[:8] = reset
    killed = full - np.outer(destination, event)
    R = independent_survival_remap(old, parameters, current_grid)
    return R @ expm(killed.T * duration) @ np.ones(len(full))


def cases(output):
    rows = []
    for phases in (0, 2):
        current_grid = grid(phases)
        for dtype in (torch.float32, torch.float64):
            count = len(DURATIONS)
            mu = torch.linspace(-.25, .45, count, dtype=dtype)
            boundary = torch.linspace(.43, 1.2, count, dtype=dtype)
            parameters = [mu, torch.full_like(mu, .5), boundary,
                          torch.full_like(mu, -.1), torch.full_like(mu, .6)]
            old = torch.linspace(1.17, .8, count, dtype=dtype)
            dt = torch.tensor(DURATIONS, dtype=dtype)
            flow = make_flow(*parameters, current_grid)
            actual = first_event_vector(flow, old, dt)
            expected = oracle.first_event_operator(flow, old, dt)
            original_survival = expected["survival_transition"].sum(-1)
            difference = float((actual["survival_vector"] - original_survival).abs().max())
            assert difference <= LIMITS["vector_oracle_absolute"]
            assert "survival_transition" not in actual
            assert torch.equal(actual["chunks"], expected["chunks"])
            assert torch.equal(actual["probability_error_bound"], expected["probability_error_bound"])
            assert torch.equal(actual["matrix_fallback_mask"], actual["chunks"] > MAX_DIRECT_CHUNKS)
            dense_rows = []
            reference = []
            for i in range(count):
                values = [float(item[i]) for item in parameters]
                target = dense(values, current_grid, float(old[i]), float(dt[i]))
                reference.append(target)
                error = float(np.abs(actual["survival_vector"][i].numpy() - target).max())
                bound = float(actual["probability_error_bound"][i])
                assert error <= bound + LIMITS["dense_extra_roundoff"]
                dense_rows.append(dict(duration=float(dt[i]), chunks=int(actual["chunks"][i]),
                    matrix_fallback=bool(actual["matrix_fallback_mask"][i]),
                    maximum_survival_error=error, truncation_bound=bound))
            name = f"m{phases}_{str(dtype).split('.')[-1]}.npz"
            np.savez_compressed(output / name, new_survival=actual["survival_vector"].numpy(),
                                old_survival=original_survival.numpy(), independent_dense=np.asarray(reference))
            rows.append(dict(phases=phases, dtype=str(dtype), maximum_oracle_difference=difference,
                             records=dense_rows, raw=name, raw_sha256=digest(output / name)))
    return rows


def backward_and_self_reset():
    rows = []
    for phases in (0, 2):
        current_grid = grid(phases)
        parameters = [.2, .45, .85, .65, .75]
        flow = make_flow(*(torch.tensor(v, dtype=torch.float64) for v in parameters), current_grid)
        full, event, _, reset = independent_generator(*parameters, current_grid)
        destination = np.r_[reset, np.zeros(phases)] if phases == 0 else np.eye(8 + phases)[8]
        killed = full - np.outer(destination, event)
        terminal = np.random.default_rng(103101 + phases).normal(size=8 + phases)
        actual = backward_jump(torch.tensor(terminal), flow, current_grid.fixed_rate).numpy()
        expected = (np.eye(len(full)) + killed.T / current_grid.fixed_rate) @ terminal
        error = float(np.abs(actual - expected).max())
        assert error < LIMITS["backward_operator_absolute"]
        p = torch.eye(8 + phases, dtype=torch.float64)[7]
        new = first_event_probability(p, first_event_vector(flow, .85, 3.2))["risk"]
        old = oracle.first_event_probability(p, oracle.first_event_operator(flow, .85, 3.2))["risk"]
        assert abs(float(new - old)) <= LIMITS["vector_oracle_absolute"]
        rows.append(dict(phases=phases, signed_terminal_operator_error=error,
                         top_cell_risk=float(new), original_top_cell_risk=float(old),
                         marked_self_reset_included=phases == 0))
    return rows


def gradients():
    rows = []
    base = [.237, .513, .8431, -.173, .417, 1.137, .495755147934]
    names = ["mu", "sigma", "boundary", "reset", "tau", "old_boundary", "duration"]
    p = torch.tensor(np.random.default_rng(103109).dirichlet(np.ones(10)), dtype=torch.float64)
    for duration in (.495755147934, 3.2, 7.31):
        values = list(base); values[-1] = duration
        def torch_objective(data, vector):
            flow = make_flow(*data[:5], grid(2))
            if vector:
                operator = first_event_vector(flow, data[5], data[6])
                return first_event_probability(p, operator)["risk"]
            operator = oracle.first_event_operator(flow, data[5], data[6])
            return oracle.first_event_probability(p, operator)["risk"]
        new_args = [torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in values]
        old_args = [torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in values]
        new_gradient = torch.autograd.grad(torch_objective(new_args, True), new_args)
        old_gradient = torch.autograd.grad(torch_objective(old_args, False), old_args)
        items = []
        for i, name in enumerate(names):
            actual, expected = float(new_gradient[i]), float(old_gradient[i])
            assert abs(actual - expected) <= LIMITS["gradient_oracle_absolute"] + LIMITS["gradient_oracle_relative"] * abs(expected)
            plus, minus = list(values), list(values)
            h = LIMITS["independent_fd_step"]; plus[i] += h; minus[i] -= h
            positive = float(p.numpy() @ (1 - dense(plus[:5], grid(2), plus[5], plus[6])))
            negative = float(p.numpy() @ (1 - dense(minus[:5], grid(2), minus[5], minus[6])))
            fd = (positive - negative) / (2 * h)
            scaled = abs(actual - fd) / max(1e-8, abs(fd))
            assert scaled < LIMITS["independent_fd_scaled"], (duration, name, scaled)
            items.append(dict(parameter=name, vector_autograd=actual, matrix_autograd=expected,
                              dense_finite_difference=fd, dense_scaled_error=scaled))
        rows.append(dict(duration=duration, parameters=items))
    return rows


def noninterference_and_guards():
    shape = (2, 4, 3)
    generator = torch.Generator().manual_seed(103113)
    mu = (-.2 + .4 * torch.rand(shape, generator=generator, dtype=torch.float64)).requires_grad_()
    b = (.7 + .4 * torch.rand(shape, generator=generator, dtype=torch.float64)).requires_grad_()
    dt = torch.full(shape, .12, dtype=torch.float64, requires_grad=True)
    first = first_event_vector(make_flow(mu, .5, b, -.1, .6, grid(2)), 1.2, dt)
    changed_mu, changed_b, changed_dt = mu.detach().clone(), b.detach().clone(), dt.detach().clone()
    changed_mu[0, 2:] = .45; changed_b[0, 2:] = .5; changed_dt[0, 2:] = 7.31
    changed_mu[1:] = -.25; changed_b[1:] = .43; changed_dt[1:] = 100.
    changed = first_event_vector(make_flow(changed_mu, .5, changed_b, -.1, .6, grid(2)), 1.2, changed_dt)
    equal = torch.equal(first["risk_vector"][0, :2], changed["risk_vector"][0, :2])
    assert equal
    derivative = torch.autograd.grad(first["risk_vector"][0, :2].sum(), (mu, b, dt))
    forbidden = max(max(float(g[0, 2:].abs().max()), float(g[1:].abs().max())) for g in derivative)
    assert forbidden == 0
    flow = make_flow(.1, .45, .85, -.1, .75, grid(2))
    rejected = []
    for value in (-.1, float("inf"), grid(2).max_duration * (grid(2).max_independent_chunks + 2)):
        try:
            first_event_vector(flow, 1.1, value)
        except ValueError:
            rejected.append(True)
        else:
            raise AssertionError("Invalid duration accepted")
    return dict(bitwise_prefix_equality_with_neighbor_matrix_fallback=bool(equal),
                forbidden_future_or_neighbor_gradient=forbidden, invalid_durations_rejected=rejected)


def copied_method_scope():
    package = Path(__file__).resolve().parent
    original = package.parent / "hcsn_risk_ablation_v1/model.py"
    changed = package / "model.py"
    def methods(path):
        tree = ast.parse(path.read_text())
        return {(node.name, method.name): method for node in tree.body if isinstance(node, ast.ClassDef)
                for method in node.body if isinstance(method, ast.FunctionDef)}
    old, new = methods(original), methods(changed)
    advance = ast.unparse(old[("RiskContentCell", "advance")]).replace(
        "first_event_probability(prior, prepared['risk'])", "vector_probability(prior, prepared['risk'])")
    forward = ast.unparse(old[("RiskContentCell", "forward")]).replace(
        "first_event_operator(prepared['flow'], old_boundary,", "first_event_vector(prepared['flow'], old_boundary,").replace(
        "('survival_transition', 'risk_vector')", "('survival_vector', 'risk_vector')")
    assert advance == ast.unparse(new[("MemoryRiskContentCell", "advance")])
    assert forward == ast.unparse(new[("MemoryRiskContentCell", "forward")])
    return dict(advance_and_forward_only_declared_replacements=True,
                original_sha256=digest(original), new_sha256=digest(changed))


def main(output):
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    package = Path(__file__).resolve().parent
    paths = [Path(__file__), package / "vector_kernel.py", package / "model.py",
             package.parent / "hcsn_risk_ablation_v1/risk_kernel.py",
             package.parent / "hcsn_risk_ablation_v1/model.py"]
    hashes = {str(path): digest(path) for path in paths}
    registration = dict(schema="hcsn-risk-vector-kernel-registration.v1", profile=PROFILE,
                        max_direct_chunks=MAX_DIRECT_CHUNKS, durations=DURATIONS, phases=[0, 2],
                        dtypes=["float32", "float64"], limits=LIMITS, source_sha256=hashes,
                        task_labels_read=False, frozen_sources_modified=False)
    (output / "REGISTRATION.json").write_text(json.dumps(registration, indent=2) + "\n")
    records, failures = {}, []
    for name, function in [("dense_and_matrix_oracle", lambda: cases(output)),
                           ("backward_and_self_reset", backward_and_self_reset),
                           ("gradients", gradients),
                           ("causality_and_guards", noninterference_and_guards),
                           ("copy_scope", copied_method_scope)]:
        try:
            records[name] = function()
        except Exception:
            failures.append(dict(test=name, traceback=traceback.format_exc()))
    changed = [str(path) for path in paths if digest(path) != hashes[str(path)]]
    result = dict(schema="hcsn-risk-vector-kernel-validation.v1", passed=not failures and not changed,
                  records=records, failures=failures, source_sha256=hashes,
                  source_changed_during_test=changed, self_cpu_seconds=time.process_time() - start_cpu,
                  wall_seconds=time.perf_counter() - start_wall,
                  peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    (output / "RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("passed", "self_cpu_seconds", "wall_seconds")}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    main(args.output)
