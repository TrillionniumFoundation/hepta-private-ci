#!/usr/bin/env python3
"""Authority-free SNG-R numerical fixtures; NOT a learned/production NDU solver.

A reference for the fully coupled, one-dimensional affine FBSDE
    dX = Y dt + sigma dW,  dY = Z dW,  Y_T = a X_T + b.
The continuous solution admits an affine decoupling field when its denominators
stay positive. The zero-noise case is a deterministic exact shooting fixture.
The graph evaluator separately implements a bounded, additive-utility DAG,
not a general FBSDE or authorization mechanism.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from typing import Mapping

MAX_SLICES = 64
MAX_GRAPH_NODES = 256
_MIN_DENOM = 1e-10
_RESIDUAL_TOL = 1e-8


class ShadowError(ValueError):
    """An invalid, unsupported or inconsistent reference problem."""


class IllPosedError(ShadowError):
    """The requested affine decoupling field crosses its singular boundary."""


def _finite(value: float, label: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ShadowError(f"{label} must be finite")
    return float(value)


@dataclass(frozen=True)
class AffineBoundary:
    slope: float
    intercept: float

    def evaluate(self, state: float) -> float:
        return self.slope * state + self.intercept


@dataclass(frozen=True)
class SliceEvidence:
    index: int
    duration: float
    initial_state: float
    final_state: float
    initial_utility: float
    final_utility: float
    boundary_residual: float
    forward_residual: float


@dataclass(frozen=True)
class ChainEvidence:
    initial_utility: float
    final_state: float
    terminal_residual: float
    max_interface_residual: float
    max_forward_residual: float
    accepted: bool
    slices: tuple[SliceEvidence, ...]


def continuation_at_left(terminal: AffineBoundary, duration: float) -> AffineBoundary:
    """Backward affine decoupling for dX=Ydt(+noise), dY=ZdW.

    We certify only the regular positive-denominator domain, not all globally
    solvable pointwise two-point boundary problems.
    """
    slope = _finite(terminal.slope, "terminal slope")
    intercept = _finite(terminal.intercept, "terminal intercept")
    duration = _finite(duration, "duration")
    if duration < 0:
        raise ShadowError("duration must be nonnegative")
    denominator = 1.0 - slope * duration
    if not math.isfinite(denominator) or denominator <= _MIN_DENOM:
        raise IllPosedError("affine decoupling field is singular/unsupported")
    result = AffineBoundary(slope / denominator, intercept / denominator)
    _finite(result.slope, "continuation slope")
    _finite(result.intercept, "continuation intercept")
    return result


def _valid_slices(durations: tuple[float, ...]) -> None:
    if not 1 <= len(durations) <= MAX_SLICES:
        raise ShadowError("slice count is outside declared bounds")
    total = 0.0
    for i, duration in enumerate(durations):
        duration = _finite(duration, f"duration[{i}]")
        if duration <= 0:
            raise ShadowError("all durations must be strictly positive")
        total += duration
    _finite(total, "total duration")


def continuation_fields(
    durations: tuple[float, ...], terminal: AffineBoundary
) -> tuple[AffineBoundary, ...]:
    """Backward propagation: each slice receives the NEXT slice's value field."""
    _valid_slices(durations)
    fields = [terminal]
    for duration in reversed(durations):
        fields.append(continuation_at_left(fields[-1], duration))
    fields.reverse()
    return tuple(fields)


def solve_chain(
    initial_state: float,
    durations: tuple[float, ...],
    terminal: AffineBoundary,
    tolerance: float = _RESIDUAL_TOL,
) -> ChainEvidence:
    """Forward shooting with independently checked terminal/interface residuals."""
    x = _finite(initial_state, "initial state")
    tolerance = _finite(tolerance, "tolerance")
    if tolerance <= 0:
        raise ShadowError("tolerance must be positive")
    fields = continuation_fields(durations, terminal)
    reports = []
    for i, duration in enumerate(durations):
        y = fields[i].evaluate(x)
        x_next = x + duration * y
        y_next = fields[i + 1].evaluate(x_next)
        for label, value in (("state", x_next), ("utility", y_next)):
            _finite(value, label)
        reports.append(
            SliceEvidence(
                i,
                duration,
                x,
                x_next,
                y,
                y_next,
                abs(y_next - y),
                abs(x_next - x - duration * y),
            )
        )
        x = x_next
    last_y = reports[-1].final_utility
    terminal_residual = abs(last_y - terminal.evaluate(x))
    max_interface = max((r.boundary_residual for r in reports), default=math.inf)
    max_forward = max((r.forward_residual for r in reports), default=math.inf)
    return ChainEvidence(
        initial_utility=reports[0].initial_utility,
        final_state=x,
        terminal_residual=terminal_residual,
        max_interface_residual=max_interface,
        max_forward_residual=max_forward,
        accepted=max(terminal_residual, max_interface, max_forward) <= tolerance,
        slices=tuple(reports),
    )


def naive_reset_baseline(
    initial_state: float, durations: tuple[float, ...], terminal: AffineBoundary
) -> ChainEvidence:
    """Deliberately INCORRECT control: reset original terminal at each local slice."""
    _valid_slices(durations)
    x = _finite(initial_state, "initial state")
    reports = []
    previous_y = None
    max_jump = 0.0
    for i, duration in enumerate(durations):
        local = continuation_at_left(terminal, duration)
        y = local.evaluate(x)
        x_next = x + duration * y
        _finite(x_next, "state")
        if previous_y is not None:
            max_jump = max(max_jump, abs(y - previous_y))
        reports.append(
            SliceEvidence(
                i,
                duration,
                x,
                x_next,
                y,
                y,
                abs(y - previous_y) if previous_y is not None else 0.0,
                abs(x_next - x - duration * y),
            )
        )
        x = x_next
        previous_y = y
    terminal_residual = abs(reports[-1].final_utility - terminal.evaluate(x))
    return ChainEvidence(
        reports[0].initial_utility,
        x,
        terminal_residual,
        max_jump,
        max(r.forward_residual for r in reports),
        max(max_jump, terminal_residual) <= _RESIDUAL_TOL,
        tuple(reports),
    )


@dataclass(frozen=True)
class StochasticEvidence:
    initial_utility: float
    terminal_residual: float
    max_boundary_residual: float
    backward_euler_residual_rms: float
    steps: int
    diffusion: float
    seed: int


def stochastic_manufactured_fixture(
    initial_state: float,
    durations: tuple[float, ...],
    terminal: AffineBoundary,
    diffusion: float,
    steps_per_slice: int,
    seed: int,
) -> StochasticEvidence:
    """Manufactured analytic Z and frozen-seed Euler samples, not a learned solver.

    The continuous-time solution has Z_t=A(t)*sigma for Y_t=A(t)X_t+B(t).
    The reported RMS is a discrete BSDE residual and SHOULD decrease on refined
    grids in aggregate; checking Y_T=g(X_T) alone is not a solver certificate.
    """
    x = _finite(initial_state, "initial state")
    diffusion = _finite(diffusion, "diffusion")
    if diffusion < 0:
        raise ShadowError("diffusion must be nonnegative")
    if not 1 <= steps_per_slice <= 4096:
        raise ShadowError("steps per slice outside bounds")
    if not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ShadowError("seed outside bounds")
    fields = continuation_fields(durations, terminal)
    first_y = fields[0].evaluate(x)
    random_stream = random.Random(seed)
    sqerr = 0.0
    max_boundary = 0.0
    total = 0
    for i, duration in enumerate(durations):
        dt = duration / steps_per_slice
        for step in range(steps_per_slice):
            before = continuation_at_left(fields[i + 1], dt * (steps_per_slice - step))
            after = continuation_at_left(
                fields[i + 1], dt * (steps_per_slice - step - 1)
            )
            y = before.evaluate(x)
            z = before.slope * diffusion
            increment = random_stream.gauss(0.0, math.sqrt(dt))
            next_x = x + y * dt + diffusion * increment
            next_y = after.evaluate(next_x)
            _finite(next_x, "stochastic state")
            _finite(next_y, "stochastic utility")
            backward_error = next_y - y - z * increment
            sqerr += backward_error**2
            total += 1
            x = next_x
        max_boundary = max(max_boundary, abs(next_y - fields[i + 1].evaluate(x)))
    return StochasticEvidence(
        initial_utility=first_y,
        terminal_residual=abs(next_y - terminal.evaluate(x)),
        max_boundary_residual=max_boundary,
        backward_euler_residual_rms=math.sqrt(sqerr / total),
        steps=total,
        diffusion=diffusion,
        seed=seed,
    )


@dataclass(frozen=True)
class ActionEdge:
    name: str
    destination: str
    compute_cost: float
    task_reward: float = 0.0


@dataclass(frozen=True)
class ChanceEdge:
    destination: str
    probability: float


@dataclass(frozen=True)
class TerminalNode:
    utility: float


@dataclass(frozen=True)
class DecisionNode:
    actions: tuple[ActionEdge, ...]


@dataclass(frozen=True)
class ChanceNode:
    outcomes: tuple[ChanceEdge, ...]


GraphNode = TerminalNode | DecisionNode | ChanceNode


@dataclass(frozen=True)
class GraphEvidence:
    root_utility: float
    node_values: dict[str, float]
    selected_actions: dict[str, str]
    unique_evaluated_nodes: int
    memoized_references: int


def backup_dag(
    nodes: Mapping[str, GraphNode], root: str, legal_actions: frozenset[str]
) -> GraphEvidence:
    """Bounded memoized control-max/chance-expectation backup; no effects.

    This is an ADDITIVE reference comparator, not arbitrary nonlinear NDU, and
    terminal utilities are fixture inputs rather than observed model success.
    """
    if (
        not isinstance(root, str)
        or root not in nodes
        or not 1 <= len(nodes) <= MAX_GRAPH_NODES
    ):
        raise ShadowError("missing root or graph size exceeds bound")
    if not isinstance(legal_actions, frozenset):
        raise ShadowError("legal actions must be a frozen set")
    state: dict[str, int] = {}  # 1=in-progress, 2=resolved
    values: dict[str, float] = {}
    selected: dict[str, str] = {}
    cache_hits = 0

    def evaluate(name: str) -> float:
        nonlocal cache_hits
        if name not in nodes:
            raise ShadowError("edge target missing")
        if state.get(name) == 1:
            raise ShadowError("cycle detected: bounded DAG profile only")
        if state.get(name) == 2:
            cache_hits += 1
            return values[name]
        state[name] = 1
        node = nodes[name]
        if isinstance(node, TerminalNode):
            value = _finite(node.utility, "terminal utility")
        elif isinstance(node, ChanceNode):
            if not node.outcomes:
                raise ShadowError("chance node has no outcomes")
            probs = [_finite(edge.probability, "probability") for edge in node.outcomes]
            if any(prob < 0 for prob in probs) or abs(sum(probs) - 1.0) > 1e-10:
                raise ShadowError("chance probabilities must sum to one")
            value = sum(
                prob * evaluate(edge.destination)
                for prob, edge in zip(probs, node.outcomes)
            )
        elif isinstance(node, DecisionNode):
            if len({edge.name for edge in node.actions}) != len(node.actions):
                raise ShadowError("duplicate decision action")
            candidates = []
            for edge in node.actions:
                if edge.name not in legal_actions:
                    continue
                cost = _finite(edge.compute_cost, "compute cost")
                reward = _finite(edge.task_reward, "task reward")
                if cost < 0:
                    raise ShadowError("negative compute cost")
                estimate = reward - cost + evaluate(edge.destination)
                candidates.append((estimate, edge.name))
            if not candidates:
                raise ShadowError("no legal action at decision node")
            # Same-value branches resolve by action name, independent of input order.
            candidates.sort(key=lambda pair: (-pair[0], pair[1]))
            value, selected[name] = candidates[0]
        else:
            raise ShadowError("unsupported graph node")
        values[name] = _finite(value, "backed-up value")
        state[name] = 2
        return values[name]

    root_value = evaluate(root)
    return GraphEvidence(root_value, values, selected, len(values), cache_hits)


def demonstration() -> dict[str, object]:
    terminal = AffineBoundary(0.5, 0.0)
    durations = (0.5, 0.5)
    correct = solve_chain(1.0, durations, terminal)
    reset = naive_reset_baseline(1.0, durations, terminal)
    graph = {
        "root": DecisionNode(
            (ActionEdge("guess", "guess", 0.0), ActionEdge("inspect", "chance", 0.5))
        ),
        "guess": TerminalNode(1.0),
        "chance": ChanceNode((ChanceEdge("good", 0.5), ChanceEdge("bad", 0.5))),
        "good": TerminalNode(5.0),
        "bad": TerminalNode(1.0),
    }
    return {
        "evidence_class": "synthetic_analytic_fixture_not_learned_fbsde",
        "correct": asdict(correct),
        "naive_reset": asdict(reset),
        "graph": asdict(backup_dag(graph, "root", frozenset({"guess", "inspect"}))),
        "stochastic": asdict(
            stochastic_manufactured_fixture(1.0, durations, terminal, 0.2, 32, 17)
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo", action="store_true", help="emit synthetic reference evidence"
    )
    arguments = parser.parse_args()
    if not arguments.demo:
        parser.error("no execution requested (use --demo)")
    print(json.dumps(demonstration(), sort_keys=True, indent=2, allow_nan=False))
