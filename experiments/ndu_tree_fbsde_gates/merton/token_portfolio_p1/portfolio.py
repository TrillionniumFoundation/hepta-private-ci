"""Bounded P1 compute-portfolio research controller. Pure, label-blind, exact rational.

Not a continuous-time Merton optimizer, learned FBSDE, or production effect owner.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction as Q
from typing import Any

VERSION = "hepta.ndu-merton.token-portfolio-p1.v1"
POLICIES = ("direct", "fixed_reason", "greedy", "neutral", "fixed_risk", "ndu_discrete", "ordinary_same_profile")
MAX_STATES = 100_000


class Invalid(ValueError):
    pass


def exact(value: Any, name: str) -> Q:
    if type(value) is not str or len(value) > 36:
        raise Invalid(f"{name}: exact rational string required")
    try:
        out = Q(value)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise Invalid(f"{name}: invalid rational") from exc
    if out.denominator > 1_000_000:
        raise Invalid(f"{name}: denominator too large")
    return out


def keys(obj: Any, names: set[str], where: str) -> None:
    if type(obj) is not dict or set(obj) != names:
        raise Invalid(f"{where}: missing or unknown keys")


def ident(value: Any, name: str) -> str:
    if type(value) is not str or not 1 <= len(value) <= 80 or not all(
        c.isascii() and (c.isalnum() or c in "_-.") for c in value
    ):
        raise Invalid(f"{name}: bad id")
    return value


def positive_int(value: Any, name: str, maximum: int, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= maximum:
        raise Invalid(f"{name}: invalid integer")
    return value


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


@dataclass(frozen=True)
class Action:
    name: str
    token_ceiling: int
    latency_ceiling_ms: int


@dataclass(frozen=True)
class Case:
    task_id: str
    bucket: str
    group: str


@dataclass(frozen=True)
class Rate:
    mean: Q
    worst_observed_group: Q
    n: int


def manifest(raw: Any) -> tuple[tuple[Action, ...], int, int, Q]:
    keys(raw, {"schema", "actions", "token_budget", "latency_budget_ms", "token_tariff"}, "manifest")
    if raw["schema"] != VERSION or type(raw["actions"]) is not list or not 2 <= len(raw["actions"]) <= 8:
        raise Invalid("manifest: schema or action count")
    acts = []
    for row in raw["actions"]:
        keys(row, {"name", "token_ceiling", "latency_ceiling_ms"}, "action")
        name = ident(row["name"], "action")
        tokens = positive_int(row["token_ceiling"], "token ceiling", 2048, zero=True)
        latency = positive_int(row["latency_ceiling_ms"], "latency ceiling", 8192, zero=True)
        if name != "direct" and (tokens == 0 or latency == 0):
            raise Invalid("effectful action requires nonzero budget")
        if name == "direct" and (tokens or latency):
            raise Invalid("direct must be an incremental no-compute baseline")
        acts.append(Action(name, tokens, latency))
    if len({a.name for a in acts}) != len(acts) or acts[0].name != "direct" or "reason" not in {a.name for a in acts}:
        raise Invalid("direct first, reason required, no duplicates")
    budget = positive_int(raw["token_budget"], "budget", 4096, zero=True)
    latency_budget = positive_int(raw["latency_budget_ms"], "latency budget", 8192, zero=True)
    fee = exact(raw["token_tariff"], "tariff")
    if not Q(0) <= fee <= Q(1):
        raise Invalid("tariff outside bound")
    return tuple(acts), budget, latency_budget, fee


def public_cases(raw: Any) -> tuple[Case, ...]:
    keys(raw, {"schema", "cases"}, "public")
    if raw["schema"] != "hepta.p1.public.v1" or type(raw["cases"]) is not list or not 1 <= len(raw["cases"]) <= 16:
        raise Invalid("public: bad schema or size")
    cases = []
    for row in raw["cases"]:
        keys(row, {"task_id", "bucket", "group"}, "public case")
        cases.append(Case(*(ident(row[k], k) for k in ("task_id", "bucket", "group"))))
    if len({c.task_id for c in cases}) != len(cases):
        raise Invalid("public: duplicate task")
    return tuple(sorted(cases, key=lambda c: c.task_id))


def fit(raw: Any, acts: tuple[Action, ...], public: tuple[Case, ...]) -> tuple[dict[tuple[str, str], Rate], Q]:
    keys(raw, {"schema", "rows"}, "train")
    if raw["schema"] != "hepta.p1.train.v1" or type(raw["rows"]) is not list or not 4 <= len(raw["rows"]) <= 4096:
        raise Invalid("train: bad schema or size")
    groups: dict[str, tuple[str, str]] = {}
    data: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    paired: dict[str, set[str]] = defaultdict(set)
    train_ids, train_groups = set(), set()
    allowed = {a.name for a in acts}
    for row in raw["rows"]:
        keys(row, {"task_id", "bucket", "group", "action", "success"}, "train row")
        tid, bucket, group, action = (ident(row[k], k) for k in ("task_id", "bucket", "group", "action"))
        if action not in allowed or type(row["success"]) is not int or row["success"] not in (0, 1):
            raise Invalid("train: bad action or independent outcome")
        if tid in groups and groups[tid] != (bucket, group):
            raise Invalid("train: inconsistent paired source")
        if action in paired[tid]:
            raise Invalid("train: duplicate action for task")
        groups[tid] = (bucket, group)
        paired[tid].add(action)
        train_ids.add(tid)
        train_groups.add(group)
        data[bucket, action].append((group, row["success"]))
    if any(v != allowed for v in paired.values()):
        raise Invalid("train: incomplete matched action panel")
    if train_ids.intersection(c.task_id for c in public) or train_groups.intersection(c.group for c in public):
        raise Invalid("train and public task/group overlap")
    rates = {}
    for bucket in {c.bucket for c in public}:
        for action in allowed:
            rows = data.get((bucket, action), [])
            by_group: dict[str, list[int]] = defaultdict(list)
            for group, success in rows:
                by_group[group].append(success)
            if len(rows) < 4 or len(by_group) < 2:
                raise Invalid(f"unavailable: insufficient support for {bucket}/{action}")
            rates[bucket, action] = Rate(
                (sum(out for _, out in rows) + 1) / Q(len(rows) + 2),
                min((sum(v) + 1) / Q(len(v) + 2) for v in by_group.values()),
                len(rows),
            )
    direct = [r["success"] for r in raw["rows"] if r["action"] == "direct"]
    alpha = min(Q(1, 2), max(Q(0), Q(1, 4) + (1 - 2 * Q(sum(direct), len(direct))) / 8))
    return rates, alpha


def score(case: Case, action: Action, rates: dict[tuple[str, str], Rate], alpha: Q, fee: Q) -> Q:
    if action.name == "direct":
        return Q(0)
    base, new = rates[case.bucket, "direct"], rates[case.bucket, action.name]
    def rho(r: Rate) -> Q:
        return (1-alpha)*r.mean + alpha*r.worst_observed_group
    return rho(new) - rho(base) - fee*action.token_ceiling


def allocate(cases: tuple[Case, ...], acts: tuple[Action, ...], token_budget: int,
             latency_budget: int, rates: dict[tuple[str, str], Rate], fee: Q,
             alpha: Q, policy: str) -> dict[str, Any]:
    if policy not in POLICIES or not Q(0) <= alpha <= Q(1, 2):
        raise Invalid("policy/alpha")
    names = {a.name: a for a in acts}
    neutral = Q(0) if policy in ("neutral", "greedy") else Q(1, 4) if policy == "fixed_risk" else alpha
    weights = {(c.task_id, a.name): score(c, a, rates, neutral, fee) for c in cases for a in acts}
    allocations = {c.task_id: "direct" for c in cases}
    if policy == "fixed_reason":
        budget, latency = token_budget, latency_budget
        for case in cases:
            a = names["reason"]
            if a.token_ceiling <= budget and a.latency_ceiling_ms <= latency:
                allocations[case.task_id] = a.name
                budget -= a.token_ceiling
                latency -= a.latency_ceiling_ms
    elif policy == "greedy":
        candidates = [(-weights[c.task_id,a.name]/a.token_ceiling, c.task_id, a.name)
                      for c in cases for a in acts if a.name != "direct" and weights[c.task_id,a.name] > 0]
        budget, latency = token_budget, latency_budget
        for _, tid, name in sorted(candidates):
            a = names[name]
            if allocations[tid] == "direct" and a.token_ceiling <= budget and a.latency_ceiling_ms <= latency:
                allocations[tid] = name
                budget -= a.token_ceiling
                latency -= a.latency_ceiling_ms
    elif policy != "direct":
        # Exact bounded two-budget multiple-choice knapsack, with no future outcome inputs.
        # Each state keeps the best prefix by value and lexicographic deterministic tie break.
        dp: dict[tuple[int, int], tuple[Q, tuple[str, ...]]] = {(0, 0): (Q(0), ())}
        for case in cases:
            nxt: dict[tuple[int, int], tuple[Q, tuple[str, ...]]] = {}
            for (t, l), (value, prefix) in dp.items():
                for a in acts:
                    tt, ll = t + a.token_ceiling, l + a.latency_ceiling_ms
                    if tt > token_budget or ll > latency_budget:
                        continue
                    candidate = (value + weights[case.task_id,a.name], prefix + (a.name,))
                    incumbent = nxt.get((tt, ll))
                    if incumbent is None or candidate[0] > incumbent[0] or (
                        candidate[0] == incumbent[0] and candidate[1] < incumbent[1]
                    ):
                        nxt[tt, ll] = candidate
                        if len(nxt) > MAX_STATES:
                            raise Invalid("unavailable: DP state bound exceeded")
            dp = nxt
        _, _, (_, choice) = min(
            ((t,l,pair) for (t,l),pair in dp.items()),
            key=lambda row: (-row[2][0], row[0], row[1], row[2][1]),
        )
        allocations = dict(zip((c.task_id for c in cases), choice))
    spent = sum(names[a].token_ceiling for a in allocations.values())
    delayed = sum(names[a].latency_ceiling_ms for a in allocations.values())
    if spent > token_budget or delayed > latency_budget:
        raise AssertionError("budget conservation")
    objective = sum((weights[tid,a] for tid,a in allocations.items()), Q(0))
    return {
        "policy": policy, "alpha": str(neutral), "assignments": allocations,
        "reserved_tokens": spent, "reserved_latency_ms": delayed,
        "estimated_net_gain": str(objective), "qualification": "RESEARCH_ONLY_DENY_ALL",
    }


def run(manifest_doc: Any, train_doc: Any, public_doc: Any) -> dict[str, Any]:
    acts, budget, latency, fee = manifest(manifest_doc)
    cases = public_cases(public_doc)
    rates, alpha = fit(train_doc, acts, cases)
    results = [allocate(cases, acts, budget, latency, rates, fee, alpha, p) for p in POLICIES]
    if results[-1]["assignments"] != results[-2]["assignments"] or results[-1]["estimated_net_gain"] != results[-2]["estimated_net_gain"]:
        raise AssertionError("same-profile ordinary control parity")
    attempt = {
        "schema": "hepta.p1.attempt.v1", "source": VERSION,
        "manifest_sha256": digest(manifest_doc), "train_sha256": digest(train_doc),
        "public_sha256": digest(public_doc), "task_count": len(cases),
        "policies": results, "claim": "SHADOW_REPLAY_NO_PHYSICAL_TOKEN_SAVINGS",
    }
    return {"attempt": attempt, "seal_sha256": digest(attempt)}
