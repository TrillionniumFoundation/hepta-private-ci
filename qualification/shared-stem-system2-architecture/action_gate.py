"""Research-only exact-arithmetic, cost-gated System 2 action selector.

Externally supplied value intervals are UNAUTHENTICATED. This is a decision
contract oracle, NOT an FBSDE solver, CI efficacy result, or production selector.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as Q
from typing import Sequence
import re

_ID = re.compile(r"[A-Za-z0-9_.:/-]{1,96}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def q(value: str) -> Q:
    """Canonical nonnegative bounded rational, no float approximation."""
    if type(value) is not str or len(value) > 64 or not re.fullmatch(
        r"(0|[1-9][0-9]*)(?:/[1-9][0-9]*)?", value
    ):
        raise ValueError("canonical rational required")
    result = Q(value)
    if str(result) != value or result.numerator.bit_length() > 96 or result.denominator.bit_length() > 96:
        raise ValueError("noncanonical or excessive rational")
    return result


@dataclass(frozen=True)
class Candidate:
    action: str
    utility_lo: str
    utility_hi: str
    costs: tuple[tuple[str, str], ...]
    feasible: bool
    sufficient_evidence: bool
    qualified_bounds: bool
    source_sha256: str

    def parse(self) -> tuple[Q, Q, Q]:
        if type(self.action) is not str or not _ID.fullmatch(self.action):
            raise ValueError("bad action")
        if type(self.source_sha256) is not str or not _SHA.fullmatch(self.source_sha256):
            raise ValueError("bad source hash")
        if any(type(v) is not bool for v in (
            self.feasible, self.sufficient_evidence, self.qualified_bounds
        )):
            raise ValueError("untyped flag")
        lo, hi = q(self.utility_lo), q(self.utility_hi)
        if lo > hi:
            raise ValueError("inverted utility interval")
        if type(self.costs) is not tuple or len(self.costs) > 20:
            raise ValueError("cost shape")
        seen = set()
        total = Q(0)
        for line in self.costs:
            if type(line) is not tuple or len(line) != 2:
                raise ValueError("cost line shape")
            kind, val = line
            if type(kind) is not str or not _ID.fullmatch(kind) or kind in seen:
                raise ValueError("bad or duplicated cost axis")
            seen.add(kind)
            total += q(val)
        return lo, hi, total


@dataclass(frozen=True)
class Decision:
    status: str
    selected_action: str | None
    reason: str
    lower_gap: str | None
    complete_cost_lines: int
    evaluator_authority: str = "DENY_ALL"
    model_efficacy_measured: bool = False


def choose(candidates: Sequence[Candidate], *, base_action: str = "ABSTAIN",
           minimum_margin: str = "0") -> Decision:
    """Only accept uniquely interval-dominant NET utility among all legal actions.

    Missing/uncertified bounds on any otherwise feasible action mean NO_GO.
    Full physical work and other costs MUST be externally measured/supplied;
    the function neither estimates costs nor assumes shared forwards free.
    """
    margin = q(minimum_margin)
    if type(base_action) is not str or not _ID.fullmatch(base_action):
        raise ValueError("base action")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, (list, tuple)) or not 1 <= len(candidates) <= 128:
        raise ValueError("bounded complete candidates")
    rows = {}
    lines = 0
    for candidate in candidates:
        if type(candidate) is not Candidate or candidate.action in rows:
            raise ValueError("wrong or duplicate candidate")
        lo, hi, cost = candidate.parse()
        rows[candidate.action] = (candidate, lo - cost, hi - cost)
        lines += len(candidate.costs)
    if base_action not in rows:
        raise ValueError("mandatory baseline absent")
    baseline = rows[base_action][0]
    if not (baseline.feasible and baseline.sufficient_evidence and baseline.qualified_bounds):
        raise ValueError("invalid baseline")
    for candidate, _lo, _hi in rows.values():
        if candidate.feasible and not (candidate.sufficient_evidence and candidate.qualified_bounds):
            return Decision("NO_GO", None, "missing_or_unqualified_feasible_candidate", None, lines)
    legal = {name: (lo, hi) for name, (c, lo, hi) in rows.items() if c.feasible}
    if len(legal) == 1:
        return Decision("SELECT", base_action, "only_feasible_abstain", None, lines)
    ordered = sorted(legal, key=lambda action: (legal[action][0], action), reverse=True)
    winner = ordered[0]
    rival_upper = max(legal[action][1] for action in legal if action != winner)
    gap = legal[winner][0] - rival_upper
    if gap <= margin:
        return Decision("NO_GO", None, "overlapping_or_insufficient_value_gap", str(gap), lines)
    return Decision("SELECT", winner, "interval_dominance_conditional_on_supplied_bounds", str(gap), lines)
