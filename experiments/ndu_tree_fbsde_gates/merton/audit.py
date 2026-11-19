"""Separate-process rational replay and exhaustive-action reference implementation.

Reconstructs world likelihoods, resource transitions, rewards and recursion without
calling Model, Planner, aggregate or preference_next. Same author, not an
independent organization, signed observer or production acceptance authority.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from dataclasses import dataclass
from fractions import Fraction as Q
from functools import lru_cache
from pathlib import Path

from portfolio import ARMS, PROFILES, SCHEMA, Case, State, arm_profile, canonical, digest, manifest_spec, root, suite


@dataclass(frozen=True)
class Result:
    utility: Q = Q(0)
    success: Q = Q(0)
    fees: Q = Q(0)
    tokens: Q = Q(0)
    shock_loss: Q = Q(0)
    investments: Q = Q(0)
    wrong_any: Q = Q(0)
    worst_net: Q = Q(0)


def public_key(s: State) -> str:
    return json.dumps([s.remaining, s.budget, s.ticks, s.trained,
                       str(s.preference), list(s.observations)], separators=(",", ":"))


class Reference:
    def __init__(self, case: Case):
        self.c = case
        self.events = lru_cache(None)(self._events)
        self.best = lru_cache(None)(self._best)

    def choices(self, s: State) -> tuple[str, ...]:
        out = ["quit"]
        if s.ticks > 0:
            out += ["submit0", "submit1"]
            for name in self.c.sensors:
                n = 1 if (name[0] == "h" or s.trained) else 2
                if name not in dict(s.observations) and s.budget >= n:
                    out.append(name)
            if self.c.allow_investment and not s.trained and s.budget >= 2:
                out.append("invest")
        return tuple(out)

    def distribution(self, s: State, what: str) -> dict[int, Q]:
        mass: dict[int, Q] = {}
        for a, b, e, f in itertools.product(range(2), repeat=4):
            target = int(a != b) if self.c.task == "xor" else int(a == b == 1)
            signals = {"bit0": a, "bit1": b, "hint0": (target+e) % 2,
                       "hint1": (target+(e if self.c.duplicate_hints else f)) % 2}
            if any(signals[k] != v for k, v in s.observations):
                continue
            weight = Q(1)
            for bit, chance in zip((a, b, e, f), (self.c.p0, self.c.p1, self.c.error, self.c.error)):
                weight *= chance if bit else 1-chance
            if weight:
                value = target if what == "target" else signals[what]
                mass[value] = mass.get(value, Q(0))+weight
        normalizer = sum(mass.values(), Q(0))
        if not normalizer:
            raise ValueError("unsupported public history")
        return {k: v/normalizer for k, v in mass.items()}

    def _events(self, s: State, action: str) -> tuple:
        if action not in self.choices(s):
            raise ValueError("replay rejected illegal action or budget violation")
        # probability, successor, success, external fee, tokens, lost budget, investment, wrong
        if action == "quit":
            return ((Q(1), None, 0, Q(0), 0, 0, 0, 0),)
        if action == "invest":
            nxt = State(s.remaining, s.budget-2, s.ticks-1, True, s.preference, s.observations)
            return ((Q(1), nxt, 0, self.c.investment_fee, 2, 0, 1, 0),)
        out = []
        if action in ("submit0", "submit1"):
            for target, p in sorted(self.distribution(s, "target").items()):
                good = int(action == "submit"+str(target))
                if s.remaining == 1:
                    out.append((p, None, good, Q(0), 0, 0, 0, 1-good))
                    continue
                preference = s.preference - Q(1, 8) if good else s.preference + Q(1, 4)
                preference = max(Q(0), min(Q(1, 2), preference))
                for chance, loss in ((1-self.c.shock_probability, 0),
                                     (self.c.shock_probability, self.c.shock_size)):
                    if chance:
                        remaining_budget = max(0, s.budget-loss)
                        nxt = State(s.remaining-1, remaining_budget, s.ticks-1, s.trained, preference, ())
                        out.append((p*chance, nxt, good, Q(0), 0, s.budget-remaining_budget, 0, 1-good))
        else:
            tokens = 1 if (action in ("hint0", "hint1") or s.trained) else 2
            fee = self.c.price*tokens
            for observed, p in sorted(self.distribution(s, action).items()):
                obs = tuple(sorted(s.observations+((action, observed),)))
                nxt = State(s.remaining, s.budget-tokens, s.ticks-1, s.trained, s.preference, obs)
                out.append((p, nxt, 0, fee, tokens, 0, 0, 0))
        return tuple(out)

    @staticmethod
    def combine(s: State, profile: str, branches: tuple) -> Result:
        if profile not in PROFILES or sum((b[0] for b in branches), Q(0)) != 1:
            raise ValueError("invalid scoring profile or law")
        alpha = Q(0) if profile == "neutral" else Q(1, 4) if profile == "fixed" else s.preference
        mean = sum((p*(good-fee+child.utility) for p, child, good, fee, *_ in branches), Q(0))
        low = min(good-fee+child.utility for _, child, good, fee, *_ in branches)
        def expectation(index: int, attribute: str) -> Q:
            return sum((b[0]*(b[index]+getattr(b[1], attribute)) for b in branches), Q(0))
        return Result(
            (1-alpha)*mean+alpha*low,
            expectation(2, "success"), expectation(3, "fees"), expectation(4, "tokens"),
            expectation(5, "shock_loss"), expectation(6, "investments"),
            sum((b[0]*(Q(1) if b[7] else b[1].wrong_any) for b in branches), Q(0)),
            min(b[2]-b[3]+b[1].worst_net for b in branches),
        )

    def _best(self, s: State, profile: str) -> tuple[Q, str]:
        best, chosen = None, "quit"
        for action in self.choices(s):
            branches = tuple((p, Result(utility=self.best(nxt, profile)[0]) if nxt else Result(),
                              good, fee, tokens, loss, invest, wrong)
                             for p, nxt, good, fee, tokens, loss, invest, wrong in self.events(s, action))
            value = self.combine(s, profile, branches).utility
            if best is None or value > best:
                best, chosen = value, action
        if best is None:
            raise ValueError("no reference action")
        return best, chosen

    def replay(self, policy: dict[str, str], profile: str) -> Result:
        @lru_cache(None)
        def visit(s: State) -> Result:
            key = public_key(s)
            if key not in policy:
                raise ValueError("incomplete reachable public-history policy")
            action = policy[key]
            branches = tuple((p, visit(nxt) if nxt else Result(), good, fee, tokens, loss, invest, wrong)
                             for p, nxt, good, fee, tokens, loss, invest, wrong in self.events(s, action))
            return self.combine(s, profile, branches)
        return visit(root(self.c))


def strict_load(path: Path) -> dict:
    if path.stat().st_size > 100_000_000:
        raise ValueError("oversized report")
    def pairs(items: list) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda text: (_ for _ in ()).throw(ValueError(text)))


def audit(directory: Path, output: Path) -> dict:
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    manifest = strict_load(directory/"manifest.json")
    sealed = strict_load(directory/"policies.json")
    if manifest != manifest_spec():
        raise ValueError("manifest specification drift")
    if manifest.get("schema") != SCHEMA or sealed.get("schema") != SCHEMA:
        raise ValueError("wrong schema")
    if manifest.get("cases") != [c.wire() for c in suite()] or manifest.get("arms") != list(ARMS):
        raise ValueError("unregistered case panel or arm set")
    if manifest.get("profiles") != list(PROFILES) or manifest.get("real_optimizer_steps") != 0:
        raise ValueError("changed scoring profiles or fabricated training")
    if manifest.get("objective") != "sum(observed_binary_task_success)-external_utility_fees":
        raise ValueError("objective drift")
    if manifest.get("real_model_calls") != 0 or sealed.get("posture") != "RESEARCH_ONLY_DENY_ALL":
        raise ValueError("fabricated model or authority claim")
    manifest_hash = hashlib.sha256((directory/"manifest.json").read_bytes()).hexdigest()
    if sealed.get("manifest_sha256") != manifest_hash:
        raise ValueError("manifest tamper")
    expected_sources = ("portfolio.py", "audit.py", "test_portfolio.py", "README.md")
    expected = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in expected_sources}
    if sealed.get("source_sha256") != expected:
        raise ValueError("source mismatch")
    cases = {c.name: c for c in suite()}
    wanted = set(itertools.product(cases, ARMS))
    rows = sealed.get("rows", [])
    keys = [(r["case"], r["arm"]) for r in rows]
    if len(keys) != len(set(keys)) or set(keys) != wanted:
        raise ValueError("missing, duplicate or foreign policy row")
    refs = {name: Reference(case) for name, case in cases.items()}
    oracles = {name: {p: ref.best(root(cases[name]), p) for p in PROFILES} for name, ref in refs.items()}
    scored = []
    for row in rows:
        case, arm = cases[row["case"]], row["arm"]
        if row.get("case_digest") != digest(case.wire()):
            raise ValueError("case binding changed")
        if any(type(row.get(k)) is not int or row[k] < 0 for k in ("cpu_ns", "wall_ns", "visited_states")):
            raise ValueError("invalid self-reported process counters")
        if row.get("root_action") != row["policy"].get(public_key(root(case))):
            raise ValueError("root action mismatch")
        results = {p: refs[case.name].replay(row["policy"], p) for p in PROFILES}
        profile = arm_profile(arm)
        if str(results[profile].utility) != row["root_value"]:
            raise ValueError("claimed utility differs from independent replay")
        for p, result in results.items():
            if result.utility > oracles[case.name][p][0]:
                raise ValueError("policy exceeds exact oracle")
            if result.tokens+result.shock_loss > case.budget:
                raise ValueError("resource conservation violation")
        if arm in ("bellman_neutral", "recursive_fixed", "ndu_discrete"):
            if results[profile].utility != oracles[case.name][profile][0]:
                raise ValueError("optimal controller has nonzero exact residual")
        real = results["neutral"]
        if real.utility != real.success-real.fees:
            raise ValueError("cost counted twice or omitted")
        scored.append({"case": case.name, "arm": arm, "root_action": row["root_action"],
                       "expected_success": str(real.success), "expected_external_fee": str(real.fees),
                       "expected_net": str(real.utility), "expected_tokens": str(real.tokens),
                       "expected_shock_loss": str(real.shock_loss),
                       "synthetic_investments": str(real.investments),
                       "probability_any_wrong_submission": str(real.wrong_any),
                       "worst_net": str(real.worst_net),
                       "cross_profile_utilities": {p: str(r.utility) for p, r in results.items()},
                       "neutral_regret": str(oracles[case.name]["neutral"][0]-real.utility),
                       "planner_cpu_ns": row["cpu_ns"], "planner_wall_ns": row["wall_ns"]})
    result = {"schema": SCHEMA+".audit", "posture": "RESEARCH_ONLY_DENY_ALL",
              "manifest_sha256": manifest_hash,
              "policies_sha256": hashlib.sha256((directory/"policies.json").read_bytes()).hexdigest(),
              "source_sha256": expected, "audited_policy_rows": len(rows),
              "same_profile_oracle_equalities": sum(r["arm"] in ARMS[2:] for r in rows),
              "independent_augmented_state_optima": {name: {p: {"value": str(v), "action": a}
                    for p, (v, a) in profiles.items()} for name, profiles in oracles.items()},
              "observed_neural_training": False, "general_fbsde_solver": False,
              "model_efficacy_established": False, "independent_signer": False,
              "audit_cpu_ns": time.process_time_ns()-start_cpu,
              "audit_wall_ns": time.perf_counter_ns()-start_wall, "rows": scored}
    with output.open("x") as f:
        json.dump(result, f, sort_keys=True, indent=2)
        f.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.directory, args.output)
    print(json.dumps({"audited_policy_rows": report["audited_policy_rows"],
                      "same_profile_oracle_equalities": report["same_profile_oracle_equalities"]}))
