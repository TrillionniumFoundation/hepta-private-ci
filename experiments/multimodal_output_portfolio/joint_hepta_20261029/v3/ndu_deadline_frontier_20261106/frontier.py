"""Common-history sequence LP with exact rational policy and lower certificates.

HiGHS proposes a policy and multipliers. Fractions, not a solver success flag,
certify its attainable risk, expected resource budget and optimality interval.
Time is a declared model duration. No hardware or LLM result is inferred.
"""
from dataclasses import dataclass
from fractions import Fraction as F

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

from ..ndu_identification.model import outcomes


@dataclass(frozen=True)
class Contract:
    deadline: int
    max_probes: int = 3
    family: str = "joint"
    fee: F = F(1, 40)
    time_price: F = F(1, 100)

    def __post_init__(self):
        if (type(self.deadline) is not int or not 0 <= self.deadline <= 48
                or type(self.max_probes) is not int or not 0 <= self.max_probes <= 16
                or self.family not in ("joint", "gated", "bernoulli", "catalog")
                or not isinstance(self.fee, F) or not isinstance(self.time_price, F)
                or self.fee < 0 or self.time_price < 0):
            raise ValueError("Require bounded horizon and nonnegative rational prices")
        if self.family == "catalog" and self.fee+3*self.time_price != F(3, 10):
            raise ValueError("The inherited catalog macro must pay its full 3/10 resource cost")

    @classmethod
    def paid_catalog(cls, deadline, max_probes):
        return cls(deadline, max_probes, "catalog", F(27, 100), F(1, 100))

    def actions(self, state, remaining):
        if self.family == "catalog":
            # One fully paid regenerative macro from the existing catalog:
            # reset, label, prepare and probe take three model time units.
            return [("inspect", 3)] if remaining >= 3 else []
        probes = (("fast", "slow", "joint") if self.family == "joint" else
                  ("prepare",) if self.family == "gated" and state == 0 else ("inspect",))
        # Unit-duration controls have a single physical cap; larger aliases add
        # identical kernels and cannot enlarge attainable randomized policies.
        caps = range(1, remaining+1) if self.family == "joint" else (1,)
        return [(probe, cap) for probe in probes for cap in caps]

    def responses(self, state, action):
        probe, cap = action
        if self.family == "joint":
            return [((label, duration, state), law)
                    for (label, duration), law in outcomes(probe, cap)]
        if probe == "prepare":
            return [(("ready", 1, 1), (F(1), F(1)))]
        if self.family == "catalog":
            return [(("0", 3, state), (F(43, 100), F(13, 100))),
                    (("1", 3, state), (F(57, 100), F(87, 100)))]
        p = F(9, 10) if self.family == "gated" else F(7, 10)
        return [(("0", 1, state), (p, 1-p)), (("1", 1, state), (1-p, p))]


class Tree:
    """Perfect-recall history tree; no hypothesis-specific action choices."""

    def __init__(self, contract, node_limit=150000):
        self.contract, self.nodes, self.actions = contract, [], []

        def visit(parent, elapsed, launches, state, mass):
            if len(self.nodes) >= node_limit:
                raise ValueError("History tree exceeds the declared node budget")
            node_id = len(self.nodes)
            node = dict(parent=parent, elapsed=elapsed, launches=launches,
                        state=state, mass=mass, actions=[])
            self.nodes.append(node)
            legal = [("stop", 0), ("stop", 1)]
            if elapsed < contract.deadline and launches < contract.max_probes:
                legal += contract.actions(state, contract.deadline-elapsed)
            for action in legal:
                aid = len(self.actions)
                node["actions"].append(aid)
                item = dict(node=node_id, action=action, children=[], cost=(F(0), F(0)))
                self.actions.append(item)
                if action[0] == "stop":
                    continue
                response = contract.responses(state, action)
                if any(sum((law[h] for _, law in response), F(0)) != 1 for h in (0, 1)):
                    raise ValueError("Response law must conserve both hypotheses' mass")
                cost = [F(0), F(0)]
                for event, law in response:
                    _, duration, next_state = event
                    if not 1 <= duration <= action[1] <= contract.deadline-elapsed:
                        raise ValueError("Response violates actual-duration cap")
                    if any(p < 0 for p in law):
                        raise ValueError("Negative observation probability")
                    charge = contract.fee+contract.time_price*duration
                    for h in (0, 1):
                        cost[h] += law[h]*charge
                    child_mass = tuple(mass[h]*law[h] for h in (0, 1))
                    if any(child_mass):
                        child = visit(aid, elapsed+duration, launches+1, next_state, child_mass)
                        item["children"].append((event, law, child))
                item["cost"] = tuple(cost)
            return node_id

        visit(None, 0, 0, 0, (F(1), F(1)))

    def solve(self, budget=None):
        if budget is not None and (not isinstance(budget, F) or budget < 0):
            raise ValueError("Expected resource budget must be a nonnegative Fraction")
        na, nn = len(self.actions), len(self.nodes)
        row, col, val = [], [], []
        for i, node in enumerate(self.nodes):
            for aid in node["actions"]:
                row.append(i); col.append(aid); val.append(1.0)
            if node["parent"] is not None:
                row.append(i); col.append(node["parent"]); val.append(-1.0)
        eq = coo_matrix((val, (row, col)), shape=(nn, na+1)).tocsr()
        rhs = np.zeros(nn); rhs[0] = 1
        loss, cost = np.zeros((2, na+1)), np.zeros((2, na+1))
        for aid, item in enumerate(self.actions):
            mass = self.nodes[item["node"]]["mass"]
            for h in (0, 1):
                if item["action"][0] == "stop":
                    loss[h, aid] = float(mass[h]*(item["action"][1] != h))
                cost[h, aid] = float(mass[h]*item["cost"][h])
        loss[:, -1] = -1
        ub = loss if budget is None else np.vstack((loss, cost))
        ub_rhs = np.zeros(2) if budget is None else np.array([0, 0, float(budget), float(budget)])
        objective = np.zeros(na+1); objective[-1] = 1
        result = linprog(objective, A_ub=ub, b_ub=ub_rhs, A_eq=eq, b_eq=rhs,
                         bounds=(0, None), method="highs",
                         options={"dual_feasibility_tolerance": 1e-9,
                                  "primal_feasibility_tolerance": 1e-9})
        if not result.success or not np.all(np.isfinite(result.x)):
            raise ArithmeticError("LP did not return a finite candidate: "+result.message)
        # Recover a genuine behavioral policy even when floating flow is imperfect.
        policy = []
        for node in self.nodes:
            weights = [F(max(0.0, float(result.x[a]))).limit_denominator(10**9)
                       for a in node["actions"]]
            total = sum(weights, F(0))
            policy.append([w/total for w in weights] if total else
                          [F(1), F(0)]+[F(0)]*(len(weights)-2))
        multipliers = [-float(v) for v in result.ineqlin.marginals]
        lam = [F(max(0.0, v)).limit_denominator(10**9) for v in multipliers[:2]]
        total = sum(lam, F(0))
        lam = tuple(v/total for v in lam) if total else (F(1, 2), F(1, 2))
        mu = tuple(F(max(0.0, v)).limit_denominator(10**9) for v in multipliers[2:])
        mu = mu if budget is not None else (F(0), F(0))
        errors, resources, masses = self.evaluate(policy)
        # Correct any upward budget rounding by an explicit STOP mixture.
        mix = min([F(1)]+[budget/c for c in resources if c > budget]) if budget is not None else F(1)
        if mix < 1:
            policy[0] = [mix*p for p in policy[0]]
            policy[0][0] += (1-mix)/2
            policy[0][1] += (1-mix)/2
            errors, resources, masses = self.evaluate(policy)
        lower = self.lower_bound(lam, mu, budget)
        upper = max(errors)
        if lower > upper or masses != (F(1), F(1)):
            raise ArithmeticError("Exact certificate contradiction or lost mass")
        if budget is not None and any(c > budget for c in resources):
            raise ArithmeticError("Recovered policy exceeds the expected budget")
        return dict(lower=lower, upper=upper, errors=errors, resources=resources,
                    gap=upper-lower, mix=mix, lam=lam, mu=mu, policy=policy,
                    solver_objective=float(result.fun), nodes=nn, variables=na+1,
                    root_actions=[(self.actions[a]["action"], str(p))
                                  for a, p in zip(self.nodes[0]["actions"], policy[0]) if p])

    def evaluate(self, policy):
        """Exact trajectory evaluation independent of LP coefficient assembly."""
        def visit(i, weights):
            node = self.nodes[i]
            errors, cost, terminal = [F(0)]*2, [F(0)]*2, [F(0)]*2
            probs = policy[i]
            if len(probs) != len(node["actions"]) or min(probs) < 0 or sum(probs) != 1:
                raise ValueError("Invalid behavioral policy")
            for aid, p in zip(node["actions"], probs):
                if not p:
                    continue
                item = self.actions[aid]
                if item["action"][0] == "stop":
                    for h in (0, 1):
                        terminal[h] += weights[h]*p
                        errors[h] += weights[h]*p*(item["action"][1] != h)
                else:
                    for event, law, child in item["children"]:
                        branch = tuple(weights[h]*p*law[h] for h in (0, 1))
                        e, c, t = visit(child, branch)
                        for h in (0, 1):
                            errors[h] += e[h]
                            cost[h] += c[h]+branch[h]*(self.contract.fee+self.contract.time_price*event[1])
                            terminal[h] += t[h]
            return tuple(errors), tuple(cost), tuple(terminal)
        return visit(0, (F(1), F(1)))

    def lower_bound(self, lam, mu, budget):
        """Rational Lagrangian DP lower bound for every feasible common policy."""
        if len(lam) != 2 or len(mu) != 2 or min(lam+mu) < 0 or sum(lam) != 1:
            raise ValueError("Require a probability vector and nonnegative prices")
        if budget is None and any(mu):
            raise ValueError("A resource multiplier needs a resource constraint")
        values = [F(0)]*len(self.nodes)
        for i in range(len(self.nodes)-1, -1, -1):
            node, options = self.nodes[i], []
            for aid in node["actions"]:
                item = self.actions[aid]
                if item["action"][0] == "stop":
                    value = sum((lam[h]*node["mass"][h]*(item["action"][1] != h)
                                 for h in (0, 1)), F(0))
                else:
                    value = sum((mu[h]*node["mass"][h]*item["cost"][h]
                                 for h in (0, 1)), F(0))
                    value += sum((values[child] for _, _, child in item["children"]), F(0))
                options.append(value)
            values[i] = min(options)
        return max(F(0), values[0]-(sum(mu)*budget if budget is not None else 0))


def encode(value):
    if isinstance(value, F):
        return str(value)
    raise TypeError(type(value).__name__)
