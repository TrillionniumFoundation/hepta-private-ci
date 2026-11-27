"""Bounded, research-only E12 discrete FBSDE action-gap controller.

The proposer never imports an E12 teacher, full-horizon oracle or test label.
Each map evaluates the complete public-prefix tree: local interfaces are NEVER
reset to a guessed terminal utility. All certificates are for the *registered*
finite rational contraction, not natural-task correctness or continuous FBSDE.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as Q
from time import process_time_ns
import re

_NUM = re.compile(r"-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?\Z")
DEPTHS = (1, 2, 3)
BITS = 16
MAX_MAPS = 64
AUTHORITY = "DENY_ALL"


def rational(s: str) -> Q:
    if type(s) is not str or len(s) > 55 or not _NUM.fullmatch(s):
        raise ValueError("noncanonical rational")
    x = Q(s)
    if str(x) != s or max(x.numerator.bit_length(), x.denominator.bit_length()) > 80:
        raise ValueError("oversized or unreduced rational")
    return x


def phi(x: Q) -> Q:
    return x / (1 + x * x)


def round_up_nonnegative(x: Q, bits: int = BITS) -> Q:
    """Outward Q-bit upper enclosure for an exact nonnegative rational."""
    if x < 0 or type(bits) is not int or not 8 <= bits <= 24:
        raise ValueError("invalid interval quantization")
    scaled = x * (1 << bits)
    upper = -(-scaled.numerator // scaled.denominator)
    return Q(upper, 1 << bits)


def round_even(x: Q, bits: int = BITS) -> Q:
    if type(bits) is not int or bits < 8 or bits > 24:
        raise ValueError("unsupported fixed point")
    scaled = x * (1 << bits)
    floor, remainder = divmod(scaled.numerator, scaled.denominator)
    if remainder * 2 > scaled.denominator or (remainder * 2 == scaled.denominator and floor % 2):
        floor += 1
    return Q(floor, 1 << bits)


@dataclass(frozen=True)
class Law:
    depth: int
    x0: str
    a: str
    horizon: str = "3/4"
    beta: str = "1/4"
    lam: str = "1/5"
    sigma: str = "1/3"
    s: str = "1/2"
    g: str = "1/2"

    def parameters(self) -> dict[str, Q]:
        if type(self.depth) is not int or self.depth not in DEPTHS:
            raise ValueError("invalid depth")
        p = {name: rational(getattr(self, name)) for name in
             ("x0", "a", "horizon", "beta", "lam", "sigma", "s", "g")}
        if not (-2 <= p["x0"] <= 2 and 0 <= p["a"] <= 1 and
                0 < p["horizon"] <= 2 and 0 <= p["beta"] <= 1 and
                0 <= p["lam"] <= 1 and 0 < p["sigma"] <= 1 and
                0 < p["s"] <= 1 and 0 < p["g"] <= 1):
            raise ValueError("outside declared operating domain")
        p["h"] = p["horizon"] / self.depth
        p["q"] = p["a"] * p["horizon"] * (p["g"] + p["beta"] * p["horizon"])
        if p["q"] >= Q(3, 4):
            raise ValueError("global contraction is not admitted")
        p["M"] = (p["g"] + p["beta"] * p["horizon"]) / 2
        return p


@dataclass(frozen=True)
class Action:
    name: str
    law: Law
    penalty: str

    def check(self) -> Q:
        if type(self.name) is not str or not re.fullmatch("[a-z][a-z0-9_-]{0,35}", self.name):
            raise ValueError("invalid action name")
        self.law.parameters()
        cost = rational(self.penalty)
        if cost < 0 or cost > Q(1, 2):
            raise ValueError("invalid synthetic utility cost")
        return cost


@dataclass(frozen=True)
class Snapshot:
    action: str
    guess: tuple[str, ...]
    mapped: tuple[str, ...]
    residual: str
    error_bound: str
    lower: str
    upper: str
    cell_forwards: int
    cell_backwards: int

    def bounds(self) -> tuple[Q, Q]:
        return rational(self.lower), rational(self.upper)


@dataclass(frozen=True)
class Decision:
    selected: str | None
    cheap_one_map: str
    snapshots: dict[str, tuple[Snapshot, ...]]
    map_evals: int
    forward_cell_calls: int
    backward_cell_calls: int
    cpu_ns: int
    reason: str
    authority: str = AUTHORITY
    pretrained_model_forwards: int = 0
    production_accepted: bool = False
    natural_task_gain_proven: bool = False


def tree_map(law: Law, guess: tuple[Q, ...]) -> tuple[Q, ...]:
    """Exact rational whole-prefix forward/backward map, not a per-leaf reset."""
    p = law.parameters()
    n = (1 << law.depth) - 1
    if (type(guess) is not tuple or len(guess) != n or
        any(type(y) is not Q or abs(y) > p["M"] for y in guess)):
        raise ValueError("invalid filtration-adapted candidate")
    x = [Q(0)] * (2 * n + 1)
    x[0] = p["x0"]
    for i, y in enumerate(guess):
        center = x[i] + p["a"] * p["h"] * phi(y)
        x[2 * i + 1] = center - p["sigma"] * p["s"]
        x[2 * i + 2] = center + p["sigma"] * p["s"]
    u = [Q(0)] * (2 * n + 1)
    for i in range(n, 2 * n + 1):
        u[i] = p["g"] * phi(x[i])
    for i in range(n - 1, -1, -1):
        u[i] = ((u[2 * i + 1] + u[2 * i + 2]) / 2 +
                p["beta"] * p["h"] * phi(x[i])) / (1 + p["lam"] * p["h"])
    return tuple(u[:n])


def snapshot(action: Action, guess: tuple[Q, ...]) -> Snapshot:
    price = action.check()
    mapped = tree_map(action.law, guess)
    q = action.law.parameters()["q"]
    residual = max(abs(a - b) for a, b in zip(guess, mapped))
    residual_upper = round_up_nonnegative(residual)
    bound = round_up_nonnegative(residual / (1 - q))
    M = action.law.parameters()["M"]
    rounded = tuple(max(-M, min(M, round_even(v))) for v in mapped)
    return Snapshot(action.name, tuple(map(str, guess)), tuple(map(str, rounded)),
                    str(residual_upper), str(bound), str(guess[0] - bound - price),
                    str(guess[0] + bound - price),
                    len(guess), len(guess))


def make_actions(x0: str, depth: int) -> tuple[Action, ...]:
    """Same root information for both controls; STOP has fixed value zero."""
    rational(x0)
    actions = (Action("direct", Law(depth, x0, "0"), "0"),
               Action("coupled", Law(depth, x0, "1/3"), "1/512"))
    for action in actions:
        action.check()
    return actions


def _winner(current: dict[str, Snapshot]) -> str | None:
    bounds = {name: snap.bounds() for name, snap in current.items()}
    bounds["stop"] = (Q(0), Q(0))
    winners = [name for name, (lo, _) in bounds.items()
               if all(lo > hi for other, (_, hi) in bounds.items() if other != name)]
    return winners[0] if len(winners) == 1 else None


def _cheap(current: dict[str, Snapshot]) -> str:
    scores = {name: rational(s.mapped[0]) - (Q(1, 512) if name == "coupled" else Q(0))
              for name, s in current.items()}
    scores["stop"] = Q(0)
    top = max(scores.values())
    winners = [a for a, v in scores.items() if v == top]
    return winners[0] if len(winners) == 1 else "hold"


def evaluate_actions(actions: tuple[Action, ...], *,
                     initial: dict[str, tuple[Q, ...]] | None = None,
                     max_maps: int = 32) -> Decision:
    """Refine the widest competitive interval; fail closed on ties/budget.

    Each interval uses a globally valid *discrete* contraction. Initial guesses
    may be neural but cannot influence the certificate beyond actual residual.
    """
    if (type(actions) is not tuple or len(actions) != 2 or
        tuple(a.name for a in actions) != ("direct", "coupled") or
        actions[0].law.x0 != actions[1].law.x0 or
        actions[0].law.depth != actions[1].law.depth or
        actions[0].law.a != "0" or actions[1].law.a != "1/3" or
        actions[0].penalty != "0" or actions[1].penalty != "1/512" or
        type(max_maps) is not int or not 2 <= max_maps <= MAX_MAPS):
        raise ValueError("unregistered action set or computation budget")
    if initial is not None and (type(initial) is not dict or set(initial) != {"direct", "coupled"}):
        raise ValueError("invalid source-locked initializer identity")
    states: dict[str, tuple[Q, ...]] = {}
    history: dict[str, list[Snapshot]] = {}
    current = {}
    start = process_time_ns()
    for action in actions:
        action.check()
        n = (1 << action.law.depth) - 1
        candidate = (Q(0),) * n if initial is None else initial[action.name]
        if type(candidate) is not tuple or len(candidate) != n:
            raise ValueError("missing initial state")
        current[action.name] = snapshot(action, candidate)
        states[action.name] = candidate
        history[action.name] = [current[action.name]]
    cheap = _cheap(current)
    count = 2
    chosen = _winner(current)
    while chosen is None and count < max_maps:
        competitive_lower = max(Q(0), *(rational(s.lower) for s in current.values()))
        competitive = [a.name for a in actions
                       if rational(current[a.name].upper) >= competitive_lower]
        if not competitive:
            break
        target = max(competitive, key=lambda a: (
            rational(current[a].upper) - rational(current[a].lower), -["direct", "coupled"].index(a)))
        old = states[target]
        law = next(a for a in actions if a.name == target).law
        M = law.parameters()["M"]
        updated = tuple(rational(v) for v in current[target].mapped)
        if updated == old:
            break
        states[target] = updated
        current[target] = snapshot(next(a for a in actions if a.name == target), updated)
        history[target].append(current[target])
        count += 1
        chosen = _winner(current)
    return Decision(
        selected=chosen, cheap_one_map=cheap,
        snapshots={name: tuple(hist) for name, hist in history.items()},
        map_evals=count, forward_cell_calls=count * ((1 << actions[0].law.depth) - 1),
        backward_cell_calls=count * ((1 << actions[0].law.depth) - 1),
        cpu_ns=max(1, process_time_ns() - start),
        reason="CERTIFIED_GAP" if chosen is not None else "HOLD_UNRESOLVED")
