"""Finite typed evidence Circuit with an Episode-level NDU *linear* special case.

No pretrained reasoning claim or general stochastic FBSDE solver. The independent
enumeration baseline must agree with the NDU backward recursion on the entire
admitted action set; proof identifiers alone never prove source truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as Q
from functools import lru_cache
import re
from types import MappingProxyType


class Denied(ValueError):
    pass


HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[A-Za-z0-9_:.\-]{1,96}\Z")


def rat(v: object, lower: Q = Q(0), upper: Q = Q(1)) -> Q:
    if type(v) not in (str, int) or type(v) is bool:
        raise Denied("registered rational or integer required")
    try:
        x = Q(v)
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise Denied("invalid exact value") from exc
    if not lower <= x <= upper or x.denominator > 10**6:
        raise Denied("out-of-domain rational")
    return x


@dataclass(frozen=True)
class Fact:
    fact_id: str
    source_sha: str
    subject: str
    relation: str
    obj: str
    fee: str
    risk: str

    def verify_shape(self) -> None:
        for v in (self.fact_id, self.subject, self.relation, self.obj):
            if type(v) is not str or IDENT.fullmatch(v) is None:
                raise Denied("invalid fact term")
        if type(self.source_sha) is not str or HEX64.fullmatch(self.source_sha) is None:
            raise Denied("missing source digest")
        rat(self.fee, Q(0), Q(1))
        rat(self.risk, Q(0), Q(1))


@dataclass(frozen=True)
class Objective:
    start: str
    end: str
    relations: tuple[str, ...]
    max_risk: str
    gamma: str
    preference_initial: str

    def verify_shape(self) -> None:
        if (type(self.relations) is not tuple or not 2 <= len(self.relations) <= 6
                or any(type(v) is not str or IDENT.fullmatch(v) is None
                       for v in (self.start, self.end, *self.relations))):
            raise Denied("bounded typed 2-6 hop objective required")
        rat(self.max_risk)
        rat(self.gamma, Q(1, 2), Q(1))
        rat(self.preference_initial)


@dataclass(frozen=True)
class State:
    current: str
    depth: int
    used_facts: tuple[str, ...]
    risk: Q
    preference: Q


@dataclass(frozen=True)
class Decision:
    value: Q
    path: tuple[str, ...]
    proved: bool


class EvidenceCircuit:
    __slots__ = ("objective", "facts", "by_id", "initial", "_sealed")

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise Denied("immutable objective/graph during an episode")
        object.__setattr__(self, name, value)

    def __init__(self, objective: Objective, facts: tuple[Fact, ...]) -> None:
        objective.verify_shape()
        if type(facts) is not tuple or not 1 <= len(facts) <= 128:
            raise Denied("bounded immutable typed facts")
        seen = set()
        for fact in facts:
            if type(fact) is not Fact:
                raise Denied("unknown fact object")
            fact.verify_shape()
            if fact.fact_id in seen:
                raise Denied("duplicate evidence identity")
            seen.add(fact.fact_id)
        self.objective = objective
        self.facts = tuple(sorted(facts, key=lambda f: f.fact_id))
        self.by_id = MappingProxyType({f.fact_id: f for f in self.facts})
        self.initial = State(objective.start, 0, (), Q(0), rat(objective.preference_initial))
        self._sealed = True

    def complete(self, s: State) -> bool:
        return s.depth == len(self.objective.relations) and s.current == self.objective.end

    def choices(self, s: State) -> tuple[Fact, ...]:
        if s.depth >= len(self.objective.relations):
            return ()
        expected = self.objective.relations[s.depth]
        return tuple(f for f in self.facts if f.subject == s.current and f.relation == expected
                     and f.fact_id not in s.used_facts
                     and s.risk + rat(f.risk) <= rat(self.objective.max_risk))

    def advance(self, s: State, f: Fact) -> State:
        if f not in self.choices(s):
            raise Denied("illegal edge or risk budget")
        fee = rat(f.fee)
        # The endogenous preference is a bounded resource-sensitivity state,
        # not an Encoder latent and not a mutable task success predicate.
        nxt_p = min(Q(1), s.preference + fee / 2)
        return State(f.obj, s.depth + 1, s.used_facts + (f.fact_id,),
                     s.risk + rat(f.risk), nxt_p)

    def instant(self, s: State, f: Fact) -> Q:
        # Exactly once per physical action; same profile for DP and NDU.
        return -rat(f.fee) * (Q(1) + s.preference)

    def terminal(self, s: State) -> Q:
        return Q(1) if self.complete(s) else Q(0)

    def validate_path(self, path: tuple[str, ...]) -> State:
        s = self.initial
        for fact_id in path:
            if fact_id not in self.by_id:
                raise Denied("unknown proof identifier")
            s = self.advance(s, self.by_id[fact_id])
        return s

    def ndu_backward(self) -> Decision:
        """Registered deterministic U_k=instant+gamma U_next, NOT a BSDE."""
        gamma = rat(self.objective.gamma, Q(1, 2), Q(1))
        explored = 0

        @lru_cache(maxsize=65536)
        def rec(s: State) -> Decision:
            nonlocal explored
            explored += 1
            if explored > 100_000:
                raise Denied("recursive NDU search exceeds state budget")
            best = Decision(self.terminal(s), (), self.complete(s))
            for f in self.choices(s):
                c = rec(self.advance(s, f))
                value = self.instant(s, f) + gamma * c.value
                path = (f.fact_id,) + c.path
                if value > best.value or (value == best.value and path < best.path):
                    best = Decision(value, path, c.proved)
            return best

        return rec(self.initial)

    def ordinary_reference(self) -> Decision:
        """Independent exhaustive iterative enumeration (no cached value heads)."""
        gamma = rat(self.objective.gamma, Q(1, 2), Q(1))
        queue = [(self.initial, Q(0), Q(1), ())]
        best = Decision(self.terminal(self.initial), (), self.complete(self.initial))
        visited = 0
        while queue:
            s, total, discount, path = queue.pop()
            visited += 1
            if visited > 100_000:
                raise Denied("exact search exceeds reference budget")
            value = total + discount * self.terminal(s)
            if value > best.value or (value == best.value and path < best.path):
                best = Decision(value, path, self.complete(s))
            for f in self.choices(s):
                queue.append((self.advance(s, f),
                              total + discount * self.instant(s, f),
                              discount * gamma, path + (f.fact_id,)))
        return best

    def compare_same_profile(self) -> dict:
        backward = self.ndu_backward()
        reference = self.ordinary_reference()
        if backward != reference:
            raise Denied("NDU / ordinary exact Bellman mismatch")
        trace = self.validate_path(backward.path)
        if backward.proved != self.complete(trace):
            raise Denied("proof claims are inconsistent")
        return {"schema": "hepta.hdsi.linear-ndu-parity.v1",
                "ndu_value": str(backward.value),
                "ordinary_value": str(reference.value),
                "proof": list(backward.path), "source_digests": [self.by_id[x].source_sha for x in backward.path],
                "success": backward.proved, "number_of_facts": len(self.facts),
                "hops": len(backward.path), "nonlinear_fbsde_solved": False,
                "pretrained_reasoning_verified": False, "production_authorized": False,
                "disposition": "HOLD_NO_GO"}


Q32_SCALE = 1 << 32


def q32_mul_ties_even(left: int, right: int) -> int:
    """Model-free parity primitive for Rust hepta-ndu/fixed.rs (not a Rust call)."""
    if (type(left) is not int or type(right) is not int or
            not -(1 << 63) <= left < (1 << 63) or
            not -(1 << 63) <= right < (1 << 63)):
        raise Denied("signed i64 Q32 inputs required")
    signed = left * right
    quotient, remainder = divmod(abs(signed), Q32_SCALE)
    if remainder > Q32_SCALE // 2 or (remainder == Q32_SCALE // 2 and quotient % 2):
        quotient += 1
    result = -quotient if signed < 0 else quotient
    if not -(1 << 63) <= result < (1 << 63):
        raise Denied("Q32 arithmetic overflow")
    return result


def native_ndu_golden_reference() -> dict:
    """docs/learning/NDU_FBSDE_SPEC.md NDU-GV-001 exact integer example.

    Pure Python numerical contract, not production Rust integration and not a
    stochastic FBSDE solve. Terminal is an externally supplied fixed 1.0.
    """
    gamma = 3435973837  # nearest/ties-even representation of 0.8
    terminal = Q32_SCALE
    u1 = Q32_SCALE // 4 + q32_mul_ties_even(gamma, terminal)
    u0 = Q32_SCALE // 2 + q32_mul_ties_even(gamma, u1)
    p = (0, Q32_SCALE // 4, -(Q32_SCALE // 4))
    if (p, (u0, u1, terminal)) != (
            (0, 1073741824, -1073741824),
            (5755256177, 4509715661, 4294967296)):
        raise Denied("native NDU published golden mismatch")
    return {"id": "NDU-GV-001", "preference_raw": list(p),
            "utility_raw": [u0, u1, terminal], "source": "Rust Q32 reference",
            "rust_executed": False, "general_fbsde_solved": False}
