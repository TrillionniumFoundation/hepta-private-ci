#!/usr/bin/env python3
"""A small, standard-library-only finite-horizon branch-tree simulator.

The module is deliberately a *shadow* calculation.  It is useful for checking
the bookkeeping needed by a short-horizon NDU/Merton prototype, but it does
not contain a learned FBSDE, a model trainer, or a provider dispatch path.

There are three forward state variables:

``X``
    A scalar world/progress state.
``P``
    A scalar preference/authority state.
``B``
    Remaining compute/action budget.  A reserve is kept unspendable.

Every continuing action has two equally likely children.  The backward value
``Y`` is the conditional mean of the two child values and ``Z`` is the
central finite difference divided by the action volatility.  Thus the code
does not pretend to learn a BSDE: it only evaluates conditional moments on a
finite, explicitly enumerated tree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
import math
import random
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


EPS = 1.0e-10


@dataclass(frozen=True)
class Action:
    """An action available at each decision time.

    ``drift`` and ``volatility`` move ``X``.  The preference state ``P`` is
    updated from the cost and drift.  ``instant`` is the utility earned before
    the discounted continuation value.  The ``stop`` action is represented by
    the name ``"stop"`` and is never charged.
    """

    name: str
    cost: float
    drift: float
    volatility: float
    instant: float


@dataclass(frozen=True)
class Node:
    depth: int
    x: float
    p: float
    budget: float


@dataclass(frozen=True)
class Solution:
    """Backward result at a node.

    ``value`` is the node's conditional utility (the backward ``Y``), and
    ``z`` is the finite-difference estimate of ``Z`` for its chosen action.
    ``path`` records the plus-branch action sequence for readability; the
    value itself averages both branches.
    """

    value: float
    action: str
    z: float
    path: Tuple[str, ...]
    spent: float


class ShortHorizonTree:
    """Finite-horizon binary branch tree with a short-horizon controller."""

    def __init__(
        self,
        horizon: int = 6,
        local_horizon: int = 2,
        discount: float = 0.93,
        reserve_budget: float = 0.0,
        actions: Optional[Sequence[Action]] = None,
    ) -> None:
        if horizon < 1:
            raise ValueError("horizon must be positive")
        if local_horizon < 1:
            raise ValueError("local_horizon must be positive")
        if not 0.0 < discount <= 1.0:
            raise ValueError("discount must be in (0, 1]")
        if reserve_budget < 0.0:
            raise ValueError("reserve_budget must be non-negative")
        self.horizon = int(horizon)
        self.local_horizon = int(local_horizon)
        self.discount = float(discount)
        self.reserve_budget = float(reserve_budget)
        self.actions: Tuple[Action, ...] = tuple(actions or (
            Action("continue", 1.0, 0.15, 0.10, 0.05),
            Action("verify", 2.0, 0.28, 0.08, 0.08),
            Action("branch", 3.0, 0.55, 0.24, 0.02),
            Action("stop", 0.0, 0.0, 0.0, 0.0),
        ))
        if not any(a.name == "stop" for a in self.actions):
            raise ValueError("actions must include a stop action")
        if any(a.cost < 0.0 for a in self.actions):
            raise ValueError("action costs must be non-negative")
        self.seed = 17
        self._z_values: List[float] = []

    # ---------- forward process -------------------------------------------------

    def _action_index(self, action: Action) -> int:
        for i, candidate in enumerate(self.actions):
            if candidate.name == action.name:
                return i
        return 0

    def _shock_multiplier(self, depth: int, action: Action) -> float:
        """Return a deterministic seed-dependent scale for the binary shock."""

        # Python's hash is intentionally randomized between processes, so use a
        # simple integer seed instead.  The same seed gives byte-for-byte output
        # while different seeds genuinely evaluate a different shadow tree.
        key = (self.seed * 1_000_003 + depth * 9_176 + self._action_index(action) * 104_729) & 0xFFFFFFFF
        return 0.80 + 0.40 * random.Random(key).random()

    def feasible(self, node: Node, action: Action) -> bool:
        if action.name == "stop":
            return True
        return node.budget - action.cost >= self.reserve_budget - EPS

    def transition(self, node: Node, action: Action, shock: float) -> Node:
        if action.name == "stop":
            return node
        scale = self._shock_multiplier(node.depth, action)
        next_budget = node.budget - action.cost
        next_x = node.x + action.drift + action.volatility * scale * shock
        next_p = max(0.0, node.p - 0.04 * action.cost + 0.02 * action.drift)
        return Node(node.depth + 1, next_x, next_p, next_budget)

    def terminal(self, x: float, p: float) -> float:
        # Bounded terminal utility prevents numerical explosions on long trees.
        return max(-2.0, min(2.0, 0.85 * x + 0.18 * p - 0.08 * x * x))

    def _continuing_actions(self) -> Iterable[Action]:
        return (a for a in self.actions if a.name != "stop")

    # ---------- backward conditional moments -----------------------------------

    def _backward(self, node: Node, remaining: int) -> Solution:
        """Short-horizon Bellman recursion returning a conditional ``Y/Z``."""

        stop = Solution(self.terminal(node.x, node.p), "stop", 0.0, ("stop",), 0.0)
        if remaining <= 0 or node.depth >= self.horizon:
            return stop

        best = stop
        for action in self._continuing_actions():
            if not self.feasible(node, action):
                continue
            plus = self.transition(node, action, 1.0)
            minus = self.transition(node, action, -1.0)
            plus_solution = self._backward(plus, remaining - 1)
            minus_solution = self._backward(minus, remaining - 1)
            expected_child = 0.5 * (plus_solution.value + minus_solution.value)
            sigma = action.volatility * self._shock_multiplier(node.depth, action)
            z = 0.0 if abs(sigma) <= EPS else (plus_solution.value - minus_solution.value) / (2.0 * sigma)
            value = action.instant + self.discount * expected_child
            spent = action.cost + max(plus_solution.spent, minus_solution.spent)
            candidate = Solution(value, action.name, z, (action.name,) + plus_solution.path, spent)
            self._z_values.append(float(z))
            if candidate.value > best.value + EPS:
                best = candidate
        return best

    def _solve(self, node: Node, horizon: int) -> Solution:
        return self._backward(node, max(0, min(int(horizon), self.horizon - node.depth)))

    def global_solve(self, node: Node) -> Solution:
        """Dynamic global Bellman solution (kept for diagnostics)."""

        return self._solve(node, self.horizon - node.depth)

    def local_solve(self, node: Node) -> Solution:
        """Short-horizon Bellman solution used by the receding controller."""

        return self._solve(node, min(self.local_horizon, self.horizon - node.depth))

    # ---------- exhaustive open-loop path comparison ---------------------------

    def _path_candidates(self, budget: float, depth: int = 0, prefix: Tuple[str, ...] = ()) -> Iterable[Tuple[str, ...]]:
        """Enumerate all feasible finite action sequences, including stopping."""

        # Stopping now is always a valid candidate.  A path ending at the
        # horizon need not append ``stop``; its terminal utility is evaluated at
        # the horizon.
        yield prefix + ("stop",)
        if depth >= self.horizon:
            return
        for action in self._continuing_actions():
            if budget - action.cost < self.reserve_budget - EPS:
                continue
            yield from self._path_candidates(budget - action.cost, depth + 1, prefix + (action.name,))

    def _find_action(self, name: str) -> Action:
        for action in self.actions:
            if action.name == name:
                return action
        raise KeyError(name)

    def evaluate_path(self, root: Node, path: Sequence[str]) -> float:
        """Expected utility of one open-loop path over all binary branches."""

        names = tuple(path)

        def rec(node: Node, depth: int) -> float:
            if depth >= len(names) or depth >= self.horizon or names[depth] == "stop":
                return self.terminal(node.x, node.p)
            action = self._find_action(names[depth])
            if not self.feasible(node, action):
                return -math.inf
            plus = self.transition(node, action, 1.0)
            minus = self.transition(node, action, -1.0)
            return action.instant + self.discount * 0.5 * (rec(plus, depth + 1) + rec(minus, depth + 1))

        return rec(root, 0)

    def exhaustive_global(self, root: Node) -> Solution:
        best_value = -math.inf
        best_path: Tuple[str, ...] = ("stop",)
        best_spent = 0.0
        for path in self._path_candidates(root.budget):
            value = self.evaluate_path(root, path)
            if value > best_value + EPS:
                best_value = value
                best_path = path
                best_spent = sum(self._find_action(name).cost for name in path if name != "stop")
        return Solution(best_value, best_path[0], 0.0, best_path, best_spent)

    def compose_short_horizons(self, root: Node) -> Solution:
        """Compose local Bellman decisions using the conditional-mean branch."""

        node = root
        path: List[str] = []
        spent = 0.0
        while node.depth < self.horizon:
            local = self.local_solve(node)
            if local.action == "stop":
                path.append("stop")
                break
            action = self._find_action(local.action)
            if not self.feasible(node, action):
                path.append("stop")
                break
            path.append(action.name)
            spent += action.cost
            # Receding-horizon composition follows the conditional mean, i.e.
            # shock 0.  Its resulting fixed sequence is then evaluated over all
            # branches by ``evaluate_path``.
            node = self.transition(node, action, 0.0)
        if not path:
            path = ["stop"]
        value = self.evaluate_path(root, path)
        root_local = self.local_solve(root)
        return Solution(value, path[0], root_local.z, tuple(path), spent)

    # ---------- public run/JSON -------------------------------------------------

    def run(self, seed: int = 17, budget: float = 8.0) -> Dict[str, object]:
        if budget < self.reserve_budget - EPS:
            raise ValueError("budget must cover reserve_budget")
        self.seed = int(seed)
        self._z_values = []
        root = Node(0, 0.0, 1.0, float(budget))
        global_bellman = self.global_solve(root)
        local_root = self.local_solve(root)
        composed = self.compose_short_horizons(root)
        exhaustive = self.exhaustive_global(root)

        gap = max(0.0, exhaustive.value - composed.value)
        z_values = [z for z in self._z_values if math.isfinite(z)]
        max_abs_z = max((abs(z) for z in z_values), default=0.0)

        def state_trace(path: Sequence[str]) -> List[Dict[str, float]]:
            node = root
            trace = [{"t": 0, "X": node.x, "P": node.p, "B": node.budget}]
            for name in path:
                if name == "stop" or node.depth >= self.horizon:
                    break
                action = self._find_action(name)
                node = self.transition(node, action, 0.0)
                trace.append({"t": node.depth, "X": node.x, "P": node.p, "B": node.budget})
            return trace

        global_trace = state_trace(exhaustive.path)
        local_trace = state_trace(composed.path)
        budget_report = {
            "initial": budget,
            "reserve": self.reserve_budget,
            "global_spent": exhaustive.spent,
            "local_spent": composed.spent,
            "global_remaining": budget - exhaustive.spent,
            "local_remaining": budget - composed.spent,
            "constraints_ok": exhaustive.spent <= budget - self.reserve_budget + EPS and composed.spent <= budget - self.reserve_budget + EPS,
        }
        protocol = {
            "mode": "SHADOW_ONLY",
            "authority": "DENY_ALL",
            "learned_fbsde": False,
            "provider_dispatch": False,
            "description": "finite binary tree with conditional moments; no learned FBSDE",
        }
        return {
            "seed": int(seed),
            "horizon": self.horizon,
            "local_horizon": self.local_horizon,
            "discount": self.discount,
            "initial_budget": budget,
            "reserve_budget": self.reserve_budget,
            "best_path": list(exhaustive.path),
            "global": asdict(exhaustive),
            "exhaustive_global": asdict(exhaustive),
            "global_bellman": asdict(global_bellman),
            "local_root": asdict(local_root),
            "short_horizon_bellman": asdict(local_root),
            "composed": asdict(composed),
            "forward": {"global_states": global_trace, "local_states": local_trace},
            "backward": {"Y0": global_bellman.value, "Z0": global_bellman.z, "max_abs_Z": max_abs_z, "finite_Z": math.isfinite(max_abs_z)},
            "local_composition_gap": gap,
            "global_gap_detected": gap > 1.0e-9,
            # An all-stop/zero-budget run has no non-trivial Z sample; the
            # empty collection is still finite and is reported as such.
            "z_finite": all(math.isfinite(z) for z in z_values),
            "z_count": len(z_values),
            "budget": budget_report,
            "authority": protocol["authority"],
            "protocol": protocol,
        }


def run(seed: int = 17, horizon: int = 6, local_horizon: int = 2, budget: float = 8.0, reserve_budget: float = 0.0) -> Dict[str, object]:
    return ShortHorizonTree(horizon, local_horizon, reserve_budget=reserve_budget).run(seed=seed, budget=budget)


def main() -> None:
    parser = argparse.ArgumentParser(description="standard-library short-horizon FBSDE shadow tree")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--local-horizon", type=int, default=2)
    parser.add_argument("--budget", type=float, default=8.0)
    parser.add_argument("--reserve-budget", type=float, default=0.0)
    args = parser.parse_args()
    result = run(args.seed, args.horizon, args.local_horizon, args.budget, args.reserve_budget)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
