"""Exact finite action/computation/capital control. Research only; no neural training.

The endogenous profile is a registered discrete preference/recursive-utility
SPECIAL CASE, not a stochastic FBSDE solver or an NDU efficacy claim.
Only public information histories enter policies. All arithmetic is rational.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass, replace
from fractions import Fraction as Q
from functools import lru_cache
from pathlib import Path
from typing import Callable

SCHEMA = "hepta.ndu-merton-finite.v1"
PARENT = "dcc92f52ea105ef371f9d792a5d411519dd92b90"
ARMS = ("no_compute", "myopic_voi", "bellman_neutral", "recursive_fixed", "ndu_discrete")
PROFILES = ("neutral", "fixed", "endogenous")
SENSORS = ("bit0", "bit1", "hint0", "hint1")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def rational(value: object) -> Q:
    if isinstance(value, bool) or not isinstance(value, (int, str, Q)):
        raise ValueError("only exact integers or rational strings admitted")
    return Q(value)


@dataclass(frozen=True)
class Case:
    name: str
    task: str = "xor"
    p0: Q = Q(1, 2)
    p1: Q = Q(1, 2)
    error: Q = Q(1, 4)
    duplicate_hints: bool = True
    sensors: tuple[str, ...] = SENSORS
    episodes: int = 1
    budget: int = 4
    deadline: int = 10
    price: Q = Q(1, 25)
    allow_investment: bool = False
    investment_fee: Q = Q(3, 20)
    initial_preference: Q = Q(1, 4)
    shock_probability: Q = Q(0)
    shock_size: int = 0

    def __post_init__(self) -> None:
        if not self.name or self.task not in ("xor", "and"):
            raise ValueError("invalid identity or task")
        for value in (self.p0, self.p1, self.error, self.initial_preference, self.shock_probability):
            if type(value) is not Q or not 0 <= value <= 1:
                raise ValueError("probabilities must be exact fractions in [0,1]")
        if self.initial_preference > Q(1, 2):
            raise ValueError("preference outside registered bound")
        for value, upper in ((self.episodes, 3), (self.budget, 16), (self.deadline, 16), (self.shock_size, 16)):
            if type(value) is not int or not 0 <= value <= upper:
                raise ValueError("invalid bounded integer")
        if self.episodes < 1 or not self.sensors or len(set(self.sensors)) != len(self.sensors):
            raise ValueError("invalid episode or sensor set")
        if any(sensor not in SENSORS for sensor in self.sensors):
            raise ValueError("unknown sensor")
        if type(self.duplicate_hints) is not bool or type(self.allow_investment) is not bool:
            raise ValueError("strict flags required")
        if any(type(v) is not Q or v < 0 for v in (self.price, self.investment_fee)):
            raise ValueError("nonnegative exact external utility charges required")

    def wire(self) -> dict:
        return {k: str(v) if isinstance(v, Q) else list(v) if isinstance(v, tuple) else v
                for k, v in asdict(self).items()}

    @classmethod
    def from_wire(cls, row: dict) -> Case:
        row = dict(row)
        for k in ("p0", "p1", "error", "price", "investment_fee", "initial_preference", "shock_probability"):
            row[k] = rational(row[k])
        row["sensors"] = tuple(row["sensors"])
        return cls(**row)


@dataclass(frozen=True)
class State:
    remaining: int
    budget: int
    ticks: int
    trained: bool = False
    preference: Q = Q(1, 4)
    observations: tuple[tuple[str, int], ...] = ()

    def key(self) -> str:
        return canonical([self.remaining, self.budget, self.ticks, self.trained,
                          str(self.preference), self.observations]).decode()


def root(case: Case) -> State:
    return State(case.episodes, case.budget, case.deadline, preference=case.initial_preference)


def preference_next(p: Q, success: int) -> Q:
    # Fixed bounded drift from OBSERVED outcome; no learned goal or observer.
    return min(Q(1, 2), max(Q(0), p + (Q(-1, 8) if success else Q(1, 4))))


def risk_weight(profile: str, state: State) -> Q:
    if profile not in PROFILES:
        raise ValueError("unknown recursive profile")
    return Q(0) if profile == "neutral" else Q(1, 4) if profile == "fixed" else state.preference


def aggregate(rows: tuple[tuple[Q, Q], ...], alpha: Q) -> Q:
    """Monotone cash-additive (1-alpha) expectation + alpha supported minimum."""
    if not rows or not 0 <= alpha <= Q(1, 2):
        raise ValueError("invalid support or bounded risk weight")
    if any(p <= 0 for p, _ in rows) or sum((p for p, _ in rows), Q(0)) != 1:
        raise ValueError("positive normalized conditional law required")
    return (1-alpha)*sum((p*v for p, v in rows), Q(0)) + alpha*min(v for _, v in rows)


class Model:
    """Known synthetic law, NOT a model inferred from future evaluation labels."""
    def __init__(self, case: Case):
        self.case = case
        worlds = []
        for a in (0, 1):
            for b in (0, 1):
                for e in (0, 1):
                    for f in (0, 1):
                        p = (case.p0 if a else 1-case.p0)*(case.p1 if b else 1-case.p1)
                        p *= (case.error if e else 1-case.error)*(case.error if f else 1-case.error)
                        target = a ^ b if case.task == "xor" else a*b
                        signals = (a, b, target ^ e, target ^ (e if case.duplicate_hints else f))
                        if p:
                            worlds.append((p, target, signals))
        self.worlds = tuple(worlds)
        self.posterior = lru_cache(None)(self._posterior)

    def _posterior(self, observations: tuple) -> tuple:
        support = tuple(w for w in self.worlds
                        if all(w[2][SENSORS.index(k)] == v for k, v in observations))
        mass = sum((w[0] for w in support), Q(0))
        if not mass:
            raise ValueError("impossible history")
        return tuple((p/mass, target, signals) for p, target, signals in support)

    def cost(self, state: State, action: str) -> tuple[int, int, Q]:
        if action == "invest":
            return 2, 1, self.case.investment_fee
        if action in SENSORS:
            tokens = 1 if state.trained or action.startswith("hint") else 2
            return tokens, 1, self.case.price*tokens
        if action in ("submit0", "submit1"):
            return 0, 1, Q(0)
        if action == "quit":
            return 0, 0, Q(0)
        raise ValueError("unknown action")

    def actions(self, state: State) -> tuple[str, ...]:
        if not state.remaining:
            return ()
        candidates = ["quit", "submit0", "submit1"]
        candidates += [k for k in self.case.sensors if k not in dict(state.observations)]
        if self.case.allow_investment and not state.trained:
            candidates += ["invest"]
        return tuple(a for a in candidates if self.cost(state, a)[0] <= state.budget
                     and self.cost(state, a)[1] <= state.ticks)

    def transitions(self, state: State, action: str) -> tuple[tuple[Q, Q, State | None], ...]:
        if action not in self.actions(state):
            raise ValueError("illegal or unaffordable action")
        if action == "quit":
            return ((Q(1), Q(0), None),)
        tokens, ticks, fee = self.cost(state, action)
        after = replace(state, budget=state.budget-tokens, ticks=state.ticks-ticks)
        if action == "invest":
            return ((Q(1), -fee, replace(after, trained=True)),)
        outcomes: dict[int, Q] = {}
        for p, target, signals in self.posterior(state.observations):
            outcome = int(target == int(action[-1])) if action.startswith("submit") else signals[SENSORS.index(action)]
            outcomes[outcome] = outcomes.get(outcome, Q(0)) + p
        rows = []
        for outcome, p in sorted(outcomes.items()):
            if action.startswith("submit"):
                if state.remaining == 1:
                    rows.append((p, Q(outcome), None))
                    continue
                nxt = replace(after, remaining=state.remaining-1, observations=(),
                              preference=preference_next(state.preference, outcome))
                shocks = ((Q(1)-self.case.shock_probability, 0),
                          (self.case.shock_probability, self.case.shock_size))
                for probability, loss in shocks:
                    if probability:
                        rows.append((p*probability, Q(outcome),
                                     replace(nxt, budget=max(0, nxt.budget-loss))))
            else:
                obs = tuple(sorted(state.observations + ((action, outcome),)))
                rows.append((p, -fee, replace(after, observations=obs)))
        return tuple(rows)


def arm_profile(arm: str) -> str:
    if arm not in ARMS:
        raise ValueError("unknown arm")
    return "endogenous" if arm == "ndu_discrete" else "fixed" if arm == "recursive_fixed" else "neutral"


class Planner:
    def __init__(self, case: Case, arm: str):
        self.model, self.arm = Model(case), arm
        self.profile = arm_profile(arm)
        self.policy: dict[str, str] = {}
        self.solve = lru_cache(None)(self._solve)

    def immediate(self, state: State) -> tuple[Q, str]:
        choices = [(Q(0), "quit")]
        for action in ("submit0", "submit1"):
            if action in self.model.actions(state):
                val = sum((p*reward for p, reward, _ in self.model.transitions(state, action)), Q(0))
                choices.append((val, action))
        return max(choices, key=lambda item: item[0])

    def _solve(self, state: State) -> Q:
        choices = self.model.actions(state)
        if not choices:
            return Q(0)
        if self.arm in ("no_compute", "myopic_voi"):
            local, selected = self.immediate(state)
            if self.arm == "myopic_voi":
                for action in choices:
                    if action in SENSORS or action == "invest":
                        val = sum((p*(reward + self.immediate(nxt)[0])
                                   for p, reward, nxt in self.model.transitions(state, action)), Q(0))
                        if val > local:
                            local, selected = val, action
            choices = (selected,)
        best, selected = None, "quit"
        for action in choices:
            terms = tuple((p, reward + (self.solve(nxt) if nxt is not None else Q(0)))
                          for p, reward, nxt in self.model.transitions(state, action))
            value = aggregate(terms, risk_weight(self.profile, state))
            if best is None or value > best:
                best, selected = value, action
        self.policy[state.key()] = selected
        if best is None:
            raise RuntimeError("unreachable empty choice")
        return best


def suite() -> tuple[Case, ...]:
    bits = ("bit0", "bit1")
    return (
        Case("xor-complementarity", sensors=bits),
        Case("xor-budget-three", sensors=bits, budget=3),
        Case("xor-no-compute", sensors=bits, budget=0),
        Case("xor-deadline", sensors=bits, deadline=1),
        Case("and-short-circuit", task="and", sensors=bits),
        Case("duplicate-hints", sensors=("hint0", "hint1"), budget=2),
        Case("independent-hints", duplicate_hints=False, sensors=("hint0", "hint1"), budget=2),
        Case("mixed-information", duplicate_hints=False, budget=4),
        Case("biased-prior", p0=Q(1, 5), p1=Q(1, 5), duplicate_hints=False),
        Case("costly-information", sensors=bits, price=Q(3, 10)),
        Case("investment-one-task", sensors=bits, allow_investment=True),
        Case("investment-three-tasks", sensors=bits, allow_investment=True,
             episodes=3, budget=8, deadline=12),
        Case("investment-fee-rejection", sensors=bits, allow_investment=True,
             episodes=3, budget=8, deadline=12, investment_fee=Q(3)),
        Case("resource-shock", sensors=bits, allow_investment=True,
             episodes=2, budget=6, deadline=9, shock_probability=Q(1, 2), shock_size=2),
        Case("dynamic-outcome-preference", p0=Q(1, 5), p1=Q(1, 5), sensors=("hint0",),
             episodes=3, budget=2, deadline=6),
    )


def manifest_spec() -> dict:
    return {"schema": SCHEMA, "parent_sha": PARENT, "cases": [c.wire() for c in suite()],
                "arms": list(ARMS), "profiles": list(PROFILES),
                "objective": "sum(observed_binary_task_success)-external_utility_fees",
                "profile": "(1-alpha)*conditional_mean+alpha*supported_minimum",
                "preference_rule": "clip_[0,1/2](p-1/8_if_observed_success_else_p+1/4)",
                "source_class": "known-law synthetic mechanism panel; not heldout model efficacy",
                "real_model_calls": 0, "real_optimizer_steps": 0,
                "capital_upgrade": "specified synthetic resource transition; NOT parameter training"}


def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    manifest = manifest_spec()
    manifest_bytes = canonical(manifest)
    with (output/"manifest.json").open("xb") as f:
        f.write(manifest_bytes)
    rows = []
    for case in suite():
        for arm in ARMS:
            t0, c0 = time.perf_counter_ns(), time.process_time_ns()
            planner = Planner(case, arm)
            value = planner.solve(root(case))
            cpu, wall = time.process_time_ns()-c0, time.perf_counter_ns()-t0
            rows.append({"case": case.name, "arm": arm, "case_digest": digest(case.wire()),
                         "root_value": str(value), "root_action": planner.policy[root(case).key()],
                         "policy": planner.policy, "visited_states": planner.solve.cache_info().currsize,
                         "cpu_ns": cpu, "wall_ns": wall})
    files = ("portfolio.py", "audit.py", "test_portfolio.py", "README.md")
    source = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in files}
    report = {"schema": SCHEMA, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
              "source_sha256": source, "runtime": {"python": sys.version, "platform": platform.platform()},
              "posture": "RESEARCH_ONLY_DENY_ALL", "rows": rows}
    with (output/"policies.json").open("xb") as f:
        f.write(canonical(report))
    print(json.dumps({"cases": len(suite()), "arms": len(ARMS), "policy_rows": len(rows),
                      "manifest_sha256": report["manifest_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
