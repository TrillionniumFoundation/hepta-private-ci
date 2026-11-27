"""Independent finite-policy and Decimal oracle for the unified NDU profile.

The oracle enumerates complete contingent stopping policies and scores their
full terminal path laws. It never calls the production backup to obtain the
reference optimum. This validates the supplied finite model, not a learned law.
"""

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product
import json
import random

from .profile import JointBranch, NduProfile, backup, digest


@dataclass(frozen=True)
class Branch:
    probability: Fraction
    cost: Fraction
    child: "Node"


@dataclass(frozen=True)
class Node:
    stop_value: Fraction
    actions: tuple[tuple[str, tuple[Branch, ...]], ...] = ()


def decimal_value(value):
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    return Decimal(str(value))


def exact_ce(law, gamma):
    """Direct 90-digit evaluation of a full probability/return path census."""
    with localcontext() as context:
        context.prec = 90
        g = decimal_value(gamma)
        if sum(p for p, _ in law) != 1:
            raise ValueError("Oracle path census is incomplete")
        if g == 0:
            return sum(decimal_value(p) * decimal_value(v) for p, v in law)
        moment = sum(decimal_value(p) * (-g * decimal_value(v)).exp() for p, v in law)
        return -moment.ln() / g


def policy_laws(node, policy_limit=10000):
    """Each tuple chooses one policy at every observed successor history."""
    results = [("stop", ((Fraction(1), node.stop_value),))]
    for action, branches in node.actions:
        descendant_laws = [policy_laws(branch.child, policy_limit) for branch in branches]
        for policies in product(*descendant_laws):
            law = tuple((branch.probability * probability, value - branch.cost)
                        for branch, (_, child_law) in zip(branches, policies)
                        for probability, value in child_law)
            results.append((action, law))
            if len(results) > policy_limit:
                raise ValueError("Complete-policy oracle exceeds its explicit bound")
    return results


def bellman(profile, node):
    choices = [("stop", float(node.stop_value))]
    for action, branches in node.actions:
        values = [bellman(profile, b.child)[1] for b in branches]
        choices.append((action, backup(profile, [
            JointBranch(float(b.probability), 0.0, float(b.cost), value,
                        profile.continuation_sha256)
            for b, value in zip(branches, values)])))
    return max(choices, key=lambda item: item[1])


def generate_tree(seed, depth):
    rng = random.Random(seed)

    def node(remaining):
        stop = Fraction(rng.randint(-18, 20), 20)
        if remaining == 0:
            return Node(stop)
        actions = []
        for name in ("refine", "observe"):
            p = Fraction(rng.randint(1, 4), 5)
            branches = tuple(Branch(probability, Fraction(rng.randint(0, 4), 20),
                                    node(remaining - 1))
                             for probability in (p, 1 - p))
            actions.append((name, branches))
        return Node(stop, tuple(actions))

    return node(depth)


def validate_oracle(cases=24):
    if not isinstance(cases, int) or not 1 <= cases <= 100:
        raise ValueError("Oracle case count must be bounded")
    profile = NduProfile(digest("finite-objective"), digest("decimal-observer"),
                         digest("frozen-finite-continuation"))
    records = []
    for case in range(cases):
        tree = generate_tree(7117 + case, 2 if case % 4 else 3)
        laws = policy_laws(tree)
        for gamma in (0.0, 1e-16, 0.01, 2.0, 8.0):
            current = replace(profile, gamma=gamma)
            scores = [(name, exact_ce(law, gamma)) for name, law in laws]
            optimum = max(v for _, v in scores)
            selected, actual = bellman(current, tree)
            with localcontext() as ctx:
                ctx.prec = 90
                error = abs(Decimal.from_float(actual) - optimum)
                selected_best = max(v for name, v in scores if name == selected)
                policy_gap = optimum - selected_best
            records.append({"case": case, "seed": 7117 + case, "gamma": gamma,
                            "policies": len(laws), "terminal_paths": sum(len(l) for _, l in laws),
                            "selected": selected, "value_error": float(error),
                            "first_action_gap": float(policy_gap),
                            "passed": error <= Decimal("3e-13")
                            and policy_gap <= Decimal("3e-13")})
    return {"schema": "hepta.ndu.unified-finite-oracle.v1", "decimal_digits": 90,
            "problems": len(records), "all_passed": all(r["passed"] for r in records),
            "max_value_error": max(r["value_error"] for r in records),
            "max_first_action_gap": max(r["first_action_gap"] for r in records),
            "scope": "known finite contingent policies, explicit costs and stopping",
            "records": records}


if __name__ == "__main__":
    result = validate_oracle()
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    if not result["all_passed"]:
        raise SystemExit(1)
