#!/usr/bin/env python3
"""Bounded nonlinear-terminal multiple-shooting research fixtures for NDU.

Zero-noise controlled scalar FBSDE surrogate: dX=Y dt, dY=0,
Y_T=g(X_T), g(x)=slope*tanh(x)+intercept. Under |slope|*T < 0.95,
the entire implicit continuation map is contractive. This is an analytic
finite-dimensional calibration fixture, NOT a learned/nonlinear stochastic solver.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass

from hepta_sngr_shadow import ShadowError, _finite, _valid_slices

MAX_ORACLE_CALLS = 32768
MAX_FIXED_POINT_STEPS = 256
CONTRACTION_CEILING = 0.95


@dataclass(frozen=True)
class TanhTerminal:
    slope: float
    intercept: float

    def evaluate(self, state: float) -> float:
        return self.slope * math.tanh(state) + self.intercept


@dataclass(frozen=True)
class NonlinearSlice:
    duration: float
    state_in: float
    state_out: float
    utility_in: float
    utility_out: float
    interface_residual: float


@dataclass(frozen=True)
class NonlinearReceipt:
    initial_utility: float
    final_state: float
    terminal_residual: float
    maximum_interface_residual: float
    oracle_calls: int
    fixed_point_steps: int
    accepted: bool
    slices: tuple[NonlinearSlice, ...]


class ContinuationOracle:
    """Independent budgeted fixed-point evaluations, not pretrained value calls."""

    def __init__(self, terminal: TanhTerminal, budget: int, tolerance: float):
        self.terminal = terminal
        self.tolerance = _finite(tolerance, "tolerance")
        if self.tolerance <= 0 or self.tolerance > 1e-5:
            raise ShadowError("invalid numerical tolerance")
        self.slope = _finite(terminal.slope, "terminal slope")
        self.intercept = _finite(terminal.intercept, "terminal intercept")
        if not isinstance(budget, int) or not 1 <= budget <= MAX_ORACLE_CALLS:
            raise ShadowError("oracle evaluation budget outside bounds")
        self.budget = budget
        self.calls = 0
        self.steps = 0

    def value(self, state: float, remaining: float) -> float:
        state = _finite(state, "state")
        remaining = _finite(remaining, "remaining")
        if remaining < 0:
            raise ShadowError("negative remaining horizon")
        q = abs(self.slope) * remaining
        if q >= CONTRACTION_CEILING:
            raise ShadowError("nonlinear terminal is outside certified contraction region")
        y = self.terminal.evaluate(state)
        _finite(y, "initial continuation")
        for _ in range(MAX_FIXED_POINT_STEPS):
            if self.calls >= self.budget:
                raise ShadowError("continuation oracle budget exhausted")
            next_y = self.terminal.evaluate(_finite(state + remaining * y, "continuation argument"))
            self.calls += 1
            self.steps += 1
            _finite(next_y, "continuation")
            # Bound on true fixed-point error from residual for q-contraction.
            if abs(next_y - y) <= self.tolerance * (1.0 - q):
                return next_y
            y = next_y
        raise ShadowError("fixed-point iterations exhausted")


def _validate_problem(initial_state: float, durations: tuple[float, ...], terminal: TanhTerminal) -> float:
    _finite(initial_state, "initial state")
    _valid_slices(durations)
    _finite(terminal.slope, "terminal slope")
    _finite(terminal.intercept, "terminal intercept")
    total = math.fsum(durations)
    if not total > 0 or abs(terminal.slope) * total >= CONTRACTION_CEILING:
        raise ShadowError("whole-horizon contraction assumption is not certified")
    return total


def nonlinear_shoot(
    initial_state: float,
    durations: tuple[float, ...],
    terminal: TanhTerminal,
    budget: int = 4096,
    tolerance: float = 1e-11,
    reset_terminal: bool = False,
) -> NonlinearReceipt:
    """Compare true continuation matching to deliberate local-terminal reset.

    This is a zero-noise nonlinear *terminal* example. Utility stays constant on
    each open slice, and only a correct global continuation field glues slices.
    """
    total = _validate_problem(initial_state, durations, terminal)
    oracle = ContinuationOracle(terminal, budget, tolerance)
    state = float(initial_state)
    elapsed = 0.0
    reports: list[NonlinearSlice] = []
    last_utility = None
    max_jump = 0.0
    for duration in durations:
        remaining = duration if reset_terminal else total - elapsed
        y = oracle.value(state, remaining)
        next_state = _finite(state + duration * y, "next state")
        elapsed += duration
        if reset_terminal:
            # A local terminal may be perfectly satisfied; the next interval
            # nevertheless starts with an incompatible utility.
            interface_residual = 0.0 if last_utility is None else abs(y - last_utility)
            next_y = y
        else:
            next_y = oracle.value(next_state, max(0.0, total - elapsed))
            interface_residual = abs(next_y - y)
        max_jump = max(max_jump, interface_residual)
        reports.append(NonlinearSlice(duration, state, next_state, y, next_y, interface_residual))
        last_utility = y if reset_terminal else next_y
        state = next_state
    terminal_residual = abs(reports[-1].utility_out - terminal.evaluate(state))
    _finite(terminal_residual, "terminal residual")
    threshold = max(1e-9, tolerance * 16)
    return NonlinearReceipt(
        reports[0].utility_in, state, terminal_residual, max_jump,
        oracle.calls, oracle.steps, max(max_jump, terminal_residual) <= threshold,
        tuple(reports),
    )


def matched_budget_comparison(
    initial_state: float,
    durations: tuple[float, ...],
    terminal: TanhTerminal,
    budget: int = 4096,
) -> dict[str, object]:
    """All three arms receive the same oracle-call ceiling, NOT equal actual cost.

    Returns actual call counts; no zero-noise fixture is a reasoning benchmark.
    """
    correct = nonlinear_shoot(initial_state, durations, terminal, budget=budget)
    wrong = nonlinear_shoot(initial_state, durations, terminal, budget=budget, reset_terminal=True)
    direct = nonlinear_shoot(initial_state, (math.fsum(durations),), terminal, budget=budget)
    return {
        "evidence_class": "synthetic_nonlinear_zero_noise_not_model_efficacy",
        "oracle_budget_each_arm": budget,
        "single_shoot": asdict(direct),
        "segmented_continuation": asdict(correct),
        "naive_terminal_reset": asdict(wrong),
    }


def manufactured_sweep(case_count: int = 24, budget: int = 512) -> dict[str, object]:
    """Deterministic synthetic heterogeneity sweep with equal per-arm ceilings.

    No sampled live model or hidden-task benchmark is represented by these cases.
    """
    if not isinstance(case_count, int) or not 1 <= case_count <= 128:
        raise ShadowError("case count outside bound")
    if not isinstance(budget, int) or not 1 <= budget <= MAX_ORACLE_CALLS:
        raise ShadowError("invalid per-arm budget")
    results = []
    for k in range(case_count):
        initial_state = (k % 7 - 3) * 0.2
        terminal = TanhTerminal((k % 11 - 5) * 0.14, (k % 5 - 2) * 0.15)
        sections = (0.2, 0.3, 0.5) if k % 2 else (0.1, 0.1, 0.3, 0.5)
        comparison = matched_budget_comparison(initial_state, sections, terminal, budget)
        results.append({
            "case": k,
            "single_calls": comparison["single_shoot"]["oracle_calls"],
            "segmented_calls": comparison["segmented_continuation"]["oracle_calls"],
            "reset_calls": comparison["naive_terminal_reset"]["oracle_calls"],
            "segmented_accepted": comparison["segmented_continuation"]["accepted"],
            "reset_accepted": comparison["naive_terminal_reset"]["accepted"],
            "segmented_interface": comparison["segmented_continuation"]["maximum_interface_residual"],
            "reset_interface": comparison["naive_terminal_reset"]["maximum_interface_residual"],
        })
    return {
        "evidence_class": "deterministic_manufactured_zero_noise_heterogeneity",
        "case_count": case_count,
        "budget_each_arm": budget,
        "segmented_passes": sum(item["segmented_accepted"] for item in results),
        "reset_passes": sum(item["reset_accepted"] for item in results),
        "mean_single_calls": sum(item["single_calls"] for item in results) / case_count,
        "mean_segmented_calls": sum(item["segmented_calls"] for item in results) / case_count,
        "cases": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--sweep", action="store_true")
    args = parser.parse_args()
    if not (args.demo or args.sweep) or (args.demo and args.sweep):
        parser.error("choose exactly one of --demo and --sweep")
    report = manufactured_sweep() if args.sweep else matched_budget_comparison(
        0.4, (0.25, 0.25, 0.5), TanhTerminal(0.6, 0.25), budget=2048,
    )
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
