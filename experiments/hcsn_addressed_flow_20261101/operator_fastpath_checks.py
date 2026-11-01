"""Independent numerical, gradient, finite-grid and complete-call cost audit."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import statistics
import time

import numpy as np
from scipy.linalg import expm, expm_frechet, solve
from scipy.stats import poisson
import scipy
import torch

from experiments.hcsn_distributional_v2.distribution_kernel import Grid, make_flow, initial_probability
from experiments.hcsn_four_stage_flow_20261031 import marked_flow
from experiments.hcsn_four_stage_flow_20261031.operator_audit import independent_generator
from . import operator_fastpath as fast


HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "hcsn_four_stage_flow_20261031"
PROTOCOL = dict(seed=861111, threads=1, matrix_float64_atol=2e-11,
                matrix_float32_atol=3e-5, gradient_atol=2e-7,
                benchmark_warmups=4, benchmark_repeats=11,
                benchmark_batches=[24, 384, 1536], benchmark_states=5,
                quality_scope="same finite CTMC; not a model-quality experiment",
                formal_preregistration=False,
                numerical_bound_scope="truncation only; separate empirical roundoff checks")


def run(out):
    torch.set_num_threads(1)
    torch.manual_seed(PROTOCOL["seed"])
    rng = np.random.default_rng(PROTOCOL["seed"])
    out.mkdir(parents=True, exist_ok=False)
    (out / "PROTOCOL.json").write_text(json.dumps(PROTOCOL, indent=2) + "\n")
    sources = [Path(__file__), HERE / "operator_fastpath.py", BASE / "marked_flow.py",
               BASE.parent / "hcsn_distributional_v2/distribution_kernel.py"]
    (out / "sources").mkdir()
    for source in sources:
        shutil.copyfile(source, out / "sources" / source.name)
    (out / "SOURCE_IDENTITY.json").write_text(json.dumps({
        str(p.relative_to(HERE.parent.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sources}, indent=2) + "\n")
    rows, raw, benchmarks = [], [], []

    def check(name, passed, **details):
        row = dict(name=name, passed=bool(passed), **details)
        rows.append(row)
        with (out / "cases.jsonl").open("a") as stream:
            stream.write(json.dumps(row, allow_nan=False) + "\n")

    def close(name, actual, reference, atol=2e-11, **details):
        a = actual.detach().numpy() if torch.is_tensor(actual) else np.asarray(actual)
        error = float(np.max(np.abs(a - np.asarray(reference))))
        check(name, np.isfinite(a).all() and error <= atol,
              maximum_absolute_error=error, tolerance=atol, **details)

    cases = json.loads((BASE / "OPERATOR_PROTOCOL.json").read_text())["cases"]
    for case in cases:
        q, mark, _, _ = independent_generator(case)
        rate = mark.sum(-1)
        t = case["duration"]
        size = len(q)
        for mode, matrix in (("full", q), ("killed", q - mark),
                             ("tilted", q - .3 * mark - .11 * np.eye(size))):
            for dtype in (torch.float64, torch.float32):
                a = torch.tensor(matrix, dtype=dtype)
                result = fast.propagate(a, t)
                actual = result["transition"]
                tolerance = 2e-11 if dtype == torch.float64 else 3e-5
                label = f"{case['name']}/{mode}/{dtype}"
                close(label + "/scipy", actual, expm(matrix * t), tolerance,
                      diagnostics=result["diagnostics"])
                check(label + "/nonnegative", bool((actual >= 0).all()),
                      minimum=float(actual.min()))
                split = fast.transition(a, t * .37) @ fast.transition(a, t * .63)
                close(label + "/semigroup", split, actual.detach().numpy(), tolerance)
                close(label + "/time_zero", fast.transition(a, 0), np.eye(size), tolerance)
                if mode == "full":
                    close(label + "/unit_mass", actual.sum(-1), np.ones(size), tolerance)
            raw.append(dict(case=case["name"], mode=mode, Q=matrix.tolist(), duration=t,
                            scipy=expm(matrix * t).tolist(),
                            actual=fast.transition(torch.tensor(matrix), t).tolist()))
        augmented = np.zeros((size + 1, size + 1))
        augmented[:size, :size], augmented[:size, -1] = q, rate
        counted = fast.propagate(torch.tensor(q), t, event_rate=torch.tensor(rate))
        reference = expm(t * augmented)
        close(case["name"] + "/repeat_count", counted["event_vector"], reference[:-1, -1],
              diagnostics=counted["diagnostics"])
        first = 1 - expm(t * (q - mark)).sum(-1)
        check(case["name"] + "/count_dominates_first_hit",
              bool((counted["event_vector"].numpy() >= first - 2e-11).all()))
        one = fast.propagate(torch.tensor(q), t * .37, event_rate=torch.tensor(rate))
        two = fast.propagate(torch.tensor(q), t * .63, event_rate=torch.tensor(rate))
        close(case["name"] + "/count_composition",
              one["event_vector"] + one["transition"] @ two["event_vector"],
              counted["event_vector"].numpy())

    # High rates, self-marks, exact absorbing states, and a zero generator.
    for scale in (0.0, 1e-12, 1.0, 100.0, 512.0):
        q = np.array([[-1., 1., 0.], [0., -1., 1.], [.2, 0., -.2]]) * scale
        rate = np.array([1., .4, .9]) * scale
        augmented = np.zeros((4, 4))
        augmented[:3, :3], augmented[:3, -1] = q, rate
        got = fast.propagate(torch.tensor(q), 1.0, event_rate=torch.tensor(rate))
        reference = expm(augmented)
        close(f"rate_scale/{scale}/transition", got["transition"], reference[:3, :3], 3e-10)
        close(f"rate_scale/{scale}/count", got["event_vector"], reference[:3, -1], 3e-10,
              diagnostics=got["diagnostics"])
    self_mark = fast.propagate(torch.zeros(1, 1, dtype=torch.float64), 40.,
                               event_rate=torch.tensor([17.], dtype=torch.float64))
    close("pure_self_mark/probability", self_mark["transition"], [[1.]], 2e-11)
    close("pure_self_mark/count", self_mark["event_vector"], [680.], 3e-10)
    check("pure_self_mark/count_exceeds_one", float(self_mark["event_vector"][0]) > 1)

    # Interior physical directions compared to independent Frechet derivatives.
    q, mark, _, _ = independent_generator(cases[0])
    direction = rng.normal(size=q.shape)
    direction = np.where(q - np.diag(np.diag(q)) > 0, direction, 0)
    direction -= np.diag(direction.sum(-1))
    loss_weight = rng.normal(size=q.shape)
    for t in (0., 1e-10, .73, 3.):
        theta = torch.tensor(.0, dtype=torch.float64, requires_grad=True)
        duration = torch.tensor(t, dtype=torch.float64, requires_grad=True)
        matrix = torch.tensor(q) + theta * torch.tensor(direction)
        result = fast.transition(matrix, duration)
        loss = (result * torch.tensor(loss_weight)).sum()
        gt, gd = torch.autograd.grad(loss, (theta, duration))
        reference_theta = (expm_frechet(q * t, direction * t, compute_expm=False)
                           * loss_weight).sum()
        reference_time = ((expm(q * t) @ q) * loss_weight).sum()
        close(f"frechet/{t}/matrix", gt, reference_theta, PROTOCOL["gradient_atol"])
        close(f"frechet/{t}/time", gd, reference_time, PROTOCOL["gradient_atol"])
    eta = torch.tensor(1., dtype=torch.float64, requires_grad=True)
    tilted = fast.transition(torch.tensor(q) - (1 - eta) * torch.tensor(mark), .73)
    derivative = torch.autograd.grad(tilted.sum(), eta)[0]
    counts = fast.propagate(torch.tensor(q), .73, event_rate=torch.tensor(mark.sum(-1)))
    close("pgf_derivative_equals_repeat_count", derivative, float(counts["event_vector"].sum()),
          PROTOCOL["gradient_atol"])

    # The tail bound itself uses an independent Poisson survival evaluation.
    for mean in (0., 1e-10, .01, .2, .5):
        for degree in (1, 4, 8, 12, 16):
            tail, moment = fast._tail(mean, degree)
            reference_tail = float(poisson.sf(degree, mean))
            reference_moment = mean * float(poisson.sf(degree - 1, mean))
            check(f"poisson_tail/{mean}/{degree}",
                  tail >= reference_tail * (1 - 1e-13) and moment >= reference_moment * (1 - 1e-13),
                  tail_bound=tail, scipy_tail=reference_tail,
                  first_moment_bound=moment, scipy_first_moment=reference_moment)

    a = torch.tensor(q)
    fallback = fast.propagate(a, .73, max_degree=1)
    check("fallback/identified", fallback["diagnostics"]["method"] == "dense_fallback")
    close("fallback/same_tensor", fallback["transition"], torch.matrix_exp(a * .73).numpy())
    batch = torch.stack((a, a * 30))
    mixed = fast.transition(batch, torch.tensor([.73, .03], dtype=torch.float64))
    close("batch_neighbor_independence", mixed[0], fast.transition(a, .73).numpy())
    for name, matrix, t in (("negative_time", a, -1),
                             ("nonfinite_time", a, float("nan")),
                             ("negative_jump", torch.tensor([[-1., -1.], [1., -1.]]), 1),
                             ("positive_row_sum", torch.tensor([[-1., 2.], [1., -1.]]), 1),
                             ("resource_cap", a, 10000)):
        try:
            fast.transition(matrix, t)
            refused = False
        except ValueError:
            refused = True
        check("refusal/" + name, refused)

    # Independent continuous-diffusion MFPT checks show approximation error;
    # fast arithmetic does not make the finite spatial CTMC exact diffusion.
    # Solve (sigma^2/2)u''+mu*u'=-1, u'(L)=0, u(b)=0 analytically.
    grid_rows = []
    lower, boundary, initial, sigma = -2., .91, -.17, .51
    for mu in (0., .23):
        exact = (((boundary - lower) ** 2 - (initial - lower) ** 2) / sigma**2 if mu == 0 else
                 (boundary - initial) / mu + sigma**2 / (2 * mu**2) * (
                     np.exp(-2 * mu * (boundary - lower) / sigma**2)
                     - np.exp(-2 * mu * (initial - lower) / sigma**2)))
        errors, diffusion_bounds = [], []
        for cells in (8, 16, 32, 64, 128):
            flow = make_flow(torch.tensor(mu, dtype=torch.float64), sigma, boundary, initial, 0.,
                             Grid(cells=cells, lower=lower, refractory_stages=0))
            q0 = marked_flow.assemble(flow)["Q0"].numpy()
            mean_time = float(initial_probability(flow, initial).numpy() @ solve(-q0, np.ones(cells)))
            error = abs(mean_time - exact)
            errors.append(error)
            diffusion_bounds.append((boundary - lower) ** 2 / (4 * sigma**2 * cells**2))
            grid_rows.append(dict(mu=mu, cells=cells, finite_ctmc_mfpt=mean_time,
                                  continuous_reflected_diffusion_mfpt=exact, absolute_error=error))
        if mu == 0:
            # The cell-center solution is u(x_i)+h^2/(4*sigma^2).
            # Linear interpolation gives an error h^2*(f-.5)^2/sigma^2.
            # This has an O(h^2) envelope, but need not decrease every refinement:
            # this particular initial location has the same error for 8..128.
            check("finite_grid/zero_drift/analytic_second_order_envelope",
                  all(error <= bound + 2e-10 for error, bound in zip(errors, diffusion_bounds)),
                  absolute_errors=errors, analytic_error_envelope=diffusion_bounds,
                  scope="This reflected pure-diffusion MFPT, not transition-density accuracy")
        else:
            check(f"finite_grid/{mu}/coarse_to_fine_mfpt", errors[-1] < errors[0] / 5,
                  coarse_absolute_error=errors[0], fine_absolute_error=errors[-1],
                  intermediate_errors=errors,
                  scope="This parameter witness only; intermediate errors need not be monotonic")

    # Timings include validations/planning/tensor allocation and backward work.
    # Both candidates use exactly the same matrices, dtype, losses, and thread.
    for batch_size in PROTOCOL["benchmark_batches"]:
        for dtype in (torch.float64, torch.float32):
            mu = torch.linspace(.15, .9, batch_size, dtype=dtype)
            flow = make_flow(mu, .3, 1., -.5, .4, Grid(cells=4, lower=-1.5, refractory_stages=1))
            matrix = marked_flow.assemble(flow)["Q"]
            duration = torch.linspace(.01, .4, batch_size, dtype=dtype)
            weight = torch.randn_like(matrix)
            for backward in (False, True):
                samples = {"dense": [], "bounded": []}
                for iteration in range(PROTOCOL["benchmark_warmups"] + PROTOCOL["benchmark_repeats"]):
                    for name in ("dense", "bounded") if iteration % 2 else ("bounded", "dense"):
                        candidate = matrix.detach().clone().requires_grad_(backward)
                        started = time.perf_counter_ns()
                        if name == "dense":
                            result = torch.matrix_exp(candidate * duration[:, None, None])
                        else:
                            result = fast.transition(candidate, duration)
                        if backward:
                            (result * weight).sum().backward()
                        seconds = (time.perf_counter_ns() - started) / 1e9
                        if iteration >= PROTOCOL["benchmark_warmups"]:
                            samples[name].append(seconds)
                medians = {key: statistics.median(value) for key, value in samples.items()}
                benchmarks.append(dict(batch=batch_size, states=5, dtype=str(dtype), backward=backward,
                                       raw_seconds=samples, median_seconds=medians,
                                       dense_over_bounded=medians["dense"] / medians["bounded"]))

    summary = dict(protocol=PROTOCOL, checks=len(rows), passed=sum(r["passed"] for r in rows),
                   failed=sum(not r["passed"] for r in rows),
                   runtime=dict(python=platform.python_version(), torch=torch.__version__,
                                numpy=np.__version__, scipy=scipy.__version__),
                   finite_grid_results=grid_rows, benchmark=benchmarks,
                   adoption="opt-in; use measured workload costs, not numerical pass count",
                   foundation_model_or_energy_claim=False)
    (out / "RAW_OPERATORS.json").write_text(json.dumps(raw, indent=2) + "\n")
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "FAILURES.json").write_text(json.dumps([r for r in rows if not r["passed"]], indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().out))
