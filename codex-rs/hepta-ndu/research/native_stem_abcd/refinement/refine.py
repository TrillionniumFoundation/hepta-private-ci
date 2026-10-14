"""R10 fixed-budget staged quadrature and paid-monitor allocation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import resource
import sys
import time
from typing import Callable

import numpy as np
import torch
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scaling"))
sys.path.insert(0, str(ROOT / "allocation"))

from engine import Graph, TARGET, TOLERANCE, CADENCE, qualifies  # noqa: E402
from wide import WidePolicy, rule, make_problem, evaluate, SCALE  # noqa: E402
from core import training_rule, gate  # noqa: E402

METHODS = ("adam", "lbfgs", "adjoint_ncg", "ad_ncg")
SCHEDULES = ("fixed_gl5", "stage_gl3_gl5")
MONITORS = ("frequent_lazy", "terminal_only")
FIT_CAP = 12.0
SWITCH_AT = 4.0


class StageBoundary(Exception):
    """Stop one optimizer invocation without accepting an unfinished trial."""


class FitBoundary(Exception):
    """Stop the complete fitting phase without accepting an unfinished trial."""


def gaussian_rule(order: int) -> tuple[np.ndarray, np.ndarray]:
    if order not in (3, 5):
        raise ValueError("unsupported Gaussian order")
    x, w = np.polynomial.legendre.leggauss(order)
    states = np.stack(np.meshgrid(*([x] * 4), indexing="ij"), -1).reshape(-1, 4) * SCALE
    weights = np.prod(
        np.stack(np.meshgrid(*([w / 2] * 4), indexing="ij"), -1), -1
    ).reshape(-1)
    if not np.isfinite(states).all() or not np.isfinite(weights).all():
        raise ValueError("nonfinite quadrature")
    if (weights <= 0).any() or abs(weights.sum() - 1) > 1e-13:
        raise ValueError("invalid quadrature mass")
    return states, weights / weights.sum()


def schedule_stages(name: str) -> tuple[tuple[str, float], ...]:
    if name == "fixed_gl5":
        return (("gl5", FIT_CAP),)
    if name == "stage_gl3_gl5":
        return (("gl3", SWITCH_AT), ("gl5", FIT_CAP))
    raise ValueError("unknown schedule")


def stage_rule(name: str) -> tuple[np.ndarray, np.ndarray]:
    if name == "gl3":
        return gaussian_rule(3)
    if name == "gl5":
        return training_rule("gl5")
    raise ValueError("unknown stage rule")


@dataclass
class StageResult:
    name: str
    start_wall: float
    end_wall: float
    start_cpu: float
    end_cpu: float
    status: str
    counts_before: dict
    counts_after: dict
    start_sha256: str | None = None
    end_sha256: str | None = None


def _sha(values: np.ndarray) -> str:
    import hashlib
    return hashlib.sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest()


def fit(
    width: int,
    seed: int,
    method: str,
    schedule: str,
    monitor: str,
    cap: float = FIT_CAP,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    if method not in METHODS or schedule not in SCHEDULES or monitor not in MONITORS:
        raise ValueError("invalid fit request")
    if not np.isfinite(cap) or cap <= SWITCH_AT:
        raise ValueError("invalid fit cap")

    wall_zero, cpu_zero = time.perf_counter(), time.process_time()
    elapsed = lambda: time.perf_counter() - wall_zero
    cpu_elapsed = lambda: time.process_time() - cpu_zero

    policy = WidePolicy(width, seed)
    selected = policy.initial.copy()
    problem = make_problem()
    gate_laws = {name: rule(name) for name in ("cc5", "cc9")}

    counts = dict(
        graphs=0,
        hvp=0,
        full_hessians=0,
        objectives=0,
        cache_hits=0,
        callbacks=0,
        updates=0,
        monitor_coarse_calls=0,
        monitor_fine_calls=0,
        monitor_skipped_fine=0,
        stage_restarts=0,
    )
    monitor_rows: list[dict] = []
    monitor_checkpoints: list[np.ndarray] = []
    switch_weights: list[np.ndarray] = []
    stage_rows: list[dict] = []
    last_monitor_end = -CADENCE
    monitor_wall = 0.0
    monitor_cpu = 0.0

    def budget(stage_deadline: float) -> None:
        now = elapsed()
        if now >= cap:
            raise FitBoundary()
        if stage_deadline < cap and now >= stage_deadline:
            raise StageBoundary()

    def intermediate_monitor(force: bool = False) -> None:
        nonlocal last_monitor_end, monitor_wall, monitor_cpu
        if monitor != "frequent_lazy":
            return
        if not force and elapsed() - last_monitor_end < CADENCE:
            return
        start_wall, start_cpu = elapsed(), cpu_elapsed()
        tensor = torch.tensor(selected, dtype=torch.float64)

        def cost(name: str) -> float:
            key = "monitor_coarse_calls" if name == "cc5" else "monitor_fine_calls"
            counts[key] += 1
            states, weights = gate_laws[name]
            roots = evaluate(policy, tensor, problem, states, chunk=256)
            return float(weights @ roots.mean(1))

        c5, c9, good = gate(cost, "lazy")
        counts["monitor_skipped_fine"] += int(c9 is None)
        end_wall, end_cpu = elapsed(), cpu_elapsed()
        monitor_checkpoints.append(selected.copy())
        monitor_rows.append(
            dict(
                index=len(monitor_rows),
                start_wall=start_wall,
                end_wall=end_wall,
                start_cpu=start_cpu,
                end_cpu=end_cpu,
                cc5=c5,
                cc9=c9,
                predicate=good,
                updates=counts["updates"],
                stage=len(stage_rows),
            )
        )
        monitor_wall += end_wall - start_wall
        monitor_cpu += end_cpu - start_cpu
        last_monitor_end = end_wall

    def run_stage(stage_name: str, stage_deadline: float) -> str:
        nonlocal selected
        states, weights = stage_rule(stage_name)
        stage_start_wall, stage_start_cpu = elapsed(), cpu_elapsed()
        counts_before = counts.copy()
        stage_start = selected.copy()
        status = "stage_boundary"

        def check() -> None:
            budget(stage_deadline)

        graph = Graph(policy, states, weights, method == "adjoint_ncg", check, counts)
        try:
            if method == "adam":
                theta = torch.tensor(selected, dtype=torch.float64, requires_grad=True)
                optimizer = torch.optim.Adam([theta], lr=0.015)
                for _ in range(1_000_000):
                    check()
                    optimizer.zero_grad(set_to_none=True)
                    value = policy.value(theta, problem, states, weights)
                    if not torch.isfinite(value):
                        raise FloatingPointError("nonfinite Adam value")
                    value.backward()
                    optimizer.step()
                    selected = theta.detach().numpy().copy()
                    counts["objectives"] += 1
                    counts["updates"] += 1
                    intermediate_monitor()
            else:
                def callback(intermediate_result):
                    nonlocal selected
                    new = intermediate_result.x.copy()
                    counts["callbacks"] += 1
                    counts["updates"] += int(not np.array_equal(new, selected))
                    selected = new
                    intermediate_monitor()

                kwargs = dict(jac=graph.jac, callback=callback)
                options = dict(gtol=1e-9, maxiter=100_000)
                if method == "lbfgs":
                    kwargs["method"] = "L-BFGS-B"
                    options.update(ftol=1e-14, maxls=40)
                else:
                    kwargs.update(method="trust-ncg", hessp=graph.hvp)
                    options.update(initial_trust_radius=1.0, max_trust_radius=1000.0, eta=0.15)
                result = minimize(graph.fun, selected, options=options, **kwargs)
                selected = result.x.copy()
                status = str(result.message)
        except StageBoundary:
            status = "stage_boundary"
        except FitBoundary:
            status = "fit_boundary"

        stage_rows.append(
            dict(
                name=stage_name,
                start_wall=stage_start_wall,
                end_wall=elapsed(),
                start_cpu=stage_start_cpu,
                end_cpu=cpu_elapsed(),
                status=status,
                counts_before=counts_before,
                counts_after=counts.copy(),
                start_sha256=_sha(stage_start),
                end_sha256=_sha(selected),
            )
        )
        return status

    # Initial monitor is paid only in the frequent-monitor arm.
    intermediate_monitor(force=True)
    for stage_index, (stage_name, deadline) in enumerate(schedule_stages(schedule)):
        if stage_index:
            switch_weights.append(selected.copy())
            counts["stage_restarts"] += 1
        status = run_stage(stage_name, min(deadline, cap))
        if status == "fit_boundary" or elapsed() >= cap:
            break

    fit_end_wall, fit_end_cpu = elapsed(), cpu_elapsed()
    selected_at_fit_end = selected.copy()

    # One full terminal qualification for every run, outside the fit budget.
    terminal_wall_start, terminal_cpu_start = elapsed(), cpu_elapsed()
    terminal_tensor = torch.tensor(selected_at_fit_end, dtype=torch.float64)
    terminal_costs = {}
    for name in ("cc5", "cc9"):
        states, weights = gate_laws[name]
        roots = evaluate(policy, terminal_tensor, problem, states, chunk=256)
        terminal_costs[name] = float(weights @ roots.mean(1))
    terminal_good = qualifies(terminal_costs["cc5"], terminal_costs["cc9"])
    terminal_wall_end, terminal_cpu_end = elapsed(), cpu_elapsed()

    if not np.isfinite(selected_at_fit_end).all():
        raise FloatingPointError("nonfinite final weights")
    if not np.array_equal(selected_at_fit_end, selected):
        raise AssertionError("terminal qualification changed weights")

    report = dict(
        final_qualification=terminal_good,
        terminal_cc5=terminal_costs["cc5"],
        terminal_cc9=terminal_costs["cc9"],
        fit_wall=fit_end_wall,
        fit_cpu=fit_end_cpu,
        terminal_wall=terminal_wall_end-terminal_wall_start,
        terminal_cpu=terminal_cpu_end-terminal_cpu_start,
        total_wall=terminal_wall_end,
        total_cpu=terminal_cpu_end,
        monitor_wall=monitor_wall,
        monitor_cpu=monitor_cpu,
        counts=counts,
        monitor_checks=monitor_rows,
        stages=stage_rows,
        fit_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        semantics=(
            "12-second fitting budget; intermediate checks never stop or select; "
            "mandatory full terminal gate is measured outside fitting budget"
        ),
    )
    return (
        selected_at_fit_end,
        np.asarray(monitor_checkpoints, dtype=np.float64),
        np.asarray(switch_weights, dtype=np.float64),
        report,
    )
