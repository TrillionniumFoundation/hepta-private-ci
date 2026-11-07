"""Finite information-set references; no learned-model or production claim.

A world contains the complete potential outcomes, including failed attempts.
Only the environment and enumerators see it. A deployable policy receives an
immutable tuple of observed (action, outcome) pairs. All acquisitions and output
attempts consume a decision and their nonnegative cost, including failures and
superseded candidates. STOP is an explicit final decision; expiry pays no reward.
Mathematical values exclude solver CPU/wall overhead, reported separately.
"""

from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
from itertools import product
import json
import math
import time


@dataclass(frozen=True)
class World:
    mass: F
    target: int
    signals: tuple[tuple[str, str], ...]
    failures: tuple[str, ...] = ()

    def observe(self, action):
        if action in self.failures:
            return "failed"
        return dict(self.signals)[action] if ":" not in action else "ok"


@dataclass(frozen=True)
class Problem:
    worlds: tuple[World, ...]
    probes: tuple[tuple[str, F, str | None], ...]
    horizon: int = 5
    budget: F = F(1)
    generation_cost: F = F(1, 20)
    revisions: bool = False

    def __post_init__(self):
        if (type(self.horizon) is not int or not 1 <= self.horizon <= 5
                or not isinstance(self.budget, F) or self.budget < 0
                or not isinstance(self.generation_cost, F) or self.generation_cost < 0
                or not self.worlds or sum(w.mass for w in self.worlds) != 1):
            raise ValueError("Use a finite rational probability law, horizon and budget")
        names = [n for n, _, _ in self.probes]
        if len(set(names)) != len(names) or any(not n or n in ("stop", "text", "image") or ":" in n for n in names):
            raise ValueError("Unique probe names required")
        for name, cost, dependency in self.probes:
            if not isinstance(cost, F) or cost < 0 or dependency is not None and dependency not in names:
                raise ValueError("Invalid probe cost or dependency")
        actions = set(names) | {f"{kind}:{v}" for kind in ("text", "image") for v in (0, 1)}
        for w in self.worlds:
            if (not isinstance(w.mass, F) or w.mass <= 0 or type(w.target) is not int
                    or w.target not in (0, 1) or len(dict(w.signals)) != len(w.signals)
                    or set(dict(w.signals)) != set(names) or set(w.failures) - actions
                    or any(type(x) is not str for _, x in w.signals)):
                raise ValueError("Incomplete or invalid potential-outcome world")

    def cost(self, action):
        if action == "stop":
            return F(0)
        return self.generation_cost if ":" in action else dict((n, c) for n, c, _ in self.probes)[action]

    def selected(self, history, kind):
        values = [int(a.split(":")[1]) for a, o in history if a.startswith(kind + ":") and o == "ok"]
        return values[-1] if values else None

    def legal(self, history):
        if len(history) >= self.horizon or any(a == "stop" for a, _ in history):
            return ()
        attempted = {a for a, _ in history}
        spent = sum((self.cost(a) for a, _ in history), F(0))
        available = ["stop"]
        # Sensing is before content generation; images depend on a successful text.
        if not any(":" in a for a in attempted):
            available += [n for n, _, dep in self.probes if n not in attempted and (dep is None or dep in attempted)]
        if self.selected(history, "image") is None:
            for kind in ("text", "image"):
                if kind == "image" and self.selected(history, "text") is None:
                    continue
                if self.selected(history, kind) is None or self.revisions:
                    available += [f"{kind}:{v}" for v in (0, 1) if f"{kind}:{v}" not in attempted]
        return tuple(a for a in available if spent + self.cost(a) <= self.budget)

    def support(self, history):
        valid = tuple(i for i, w in enumerate(self.worlds)
                      if all(a == "stop" or w.observe(a) == o for a, o in history))
        if not valid:
            raise ValueError("Impossible public history")
        return valid

    def reward(self, history, world):
        return F(bool(history and history[-1][0] == "stop"
                      and self.selected(history, "text") == self.selected(history, "image") == world.target))

    def branches(self, history, action):
        if action not in self.legal(history):
            raise ValueError("Illegal action or exhausted budget")
        support = self.support(history)
        total = sum(self.worlds[i].mass for i in support)
        groups = {}
        for i in support:
            w = self.worlds[i]
            observation = "delivered" if action == "stop" else w.observe(action)
            groups[observation] = groups.get(observation, F(0)) + w.mass
        return tuple((mass / total, history + ((action, o),)) for o, mass in sorted(groups.items()))


def solve(problem, sensing_limit=None):
    """Exact rational Bellman DP over public histories, not private world IDs."""
    if sensing_limit is not None and (type(sensing_limit) is not int or not 0 <= sensing_limit <= 5):
        raise ValueError("Sensing lookahead must be an integer from zero through five")
    policy, values = {}, {}

    @lru_cache(None)
    def visit(history, left):
        if history and history[-1][0] == "stop":
            support = problem.support(history)
            return sum(problem.worlds[i].mass * problem.reward(history, problem.worlds[i]) for i in support) / sum(problem.worlds[i].mass for i in support)
        if not problem.legal(history):
            return F(0)
        q = {}
        for action in problem.legal(history):
            sense = action != "stop" and ":" not in action
            if sense and left == 0:
                continue
            after = None if left is None else left - int(sense)
            q[action] = -problem.cost(action) + sum(p * visit(h, after) for p, h in problem.branches(history, action))
        chosen = max(q, key=q.get)
        policy[(history, left)], values[(history, left)] = chosen, q[chosen]
        return q[chosen]

    value = visit((), sensing_limit)
    return {"value": value, "policy": policy, "values": values, "visit": visit}


def public_policy(problem, sensing_lookahead=None):
    """Replan from public state with at most k further sensing actions.

The remainder still includes optimal legal text/image completion and STOP;
this avoids making greedy artificially weak through complementary outputs.
"""
    solved = solve(problem, sensing_lookahead)

    def choose(history):
        solved["visit"](history, sensing_lookahead)
        return solved["policy"][(history, sensing_lookahead)]

    return choose


def replay(problem, policy):
    """Enumerate one nonanticipating policy on all worlds, retaining all charges."""
    paths, seen = [], {}
    for w in problem.worlds:
        h, cost = (), F(0)
        while problem.legal(h):
            action = policy(h)
            if action not in problem.legal(h) or h in seen and seen[h] != action:
                raise ValueError("Illegal or nonanticipating policy violation")
            seen[h] = action
            cost += problem.cost(action)
            h += ((action, "delivered" if action == "stop" else w.observe(action)),)
        paths.append({"mass": w.mass, "history": h, "cost": cost,
                      "utility": problem.reward(h, w), "return": problem.reward(h, w) - cost})
    return {"value": sum(p["mass"] * p["return"] for p in paths), "paths": paths}


def brute_force(problem, max_trees=200000):
    """Independent enumeration of reachable information-set policy trees.

No Bellman max or DP cache is used: Cartesian products enumerate separate
continuations for every public observation. The work cap rejects, never prunes.
"""
    count = [0]

    def trees(history, indices):
        mass = sum(problem.worlds[i].mass for i in indices)
        if not problem.legal(history):
            reward = sum(problem.worlds[i].mass * problem.reward(history, problem.worlds[i]) for i in indices) / mass
            yield reward
            return
        for action in problem.legal(history):
            grouped = {}
            for i in indices:
                o = "delivered" if action == "stop" else problem.worlds[i].observe(action)
                grouped.setdefault(o, []).append(i)
            parts = [(sum(problem.worlds[i].mass for i in ids) / mass,
                      tuple(trees(history + ((action, o),), tuple(ids)))) for o, ids in sorted(grouped.items())]
            for choice in product(*(values for _, values in parts)):
                count[0] += 1
                if count[0] > max_trees:
                    raise ValueError("Policy-tree enumeration budget exhausted")
                yield sum(p * v for (p, _), v in zip(parts, choice)) - problem.cost(action)

    roots = tuple(trees((), tuple(range(len(problem.worlds)))))
    return {"value": max(roots), "root_trees": len(roots), "subtrees": count[0]}


def clairvoyant(problem):
    """E[pathwise best return] with all future potential outcomes; never policy."""
    values = []
    for w in problem.worlds:
        @lru_cache(None)
        def visit(h):
            if not problem.legal(h):
                return problem.reward(h, w)
            return max(-problem.cost(a) + visit(h + ((a, "delivered" if a == "stop" else w.observe(a)),))
                       for a in problem.legal(h))
        values.append(visit(()))
    return {"value": sum(w.mass * v for w, v in zip(problem.worlds, values)),
            "world_returns": tuple(values), "deployable": False}


def best_fixed(problem):
    """Best fixed action-kind schedule with observation-adaptive output content.

The exact known model selects the schedule: this is a strong finite-model
reference, not validation tuning or a trained baseline. Schedules infeasible
on any positive-mass observation branch are rejected in their entirety.
"""
    kinds = tuple(n for n, _, _ in problem.probes) + ("text", "image")
    best = {"value": F(0), "schedule": ("stop",)}
    for length in range(problem.horizon):
        for prefix in product(kinds, repeat=length):
            schedule = prefix + ("stop",)

            def visit(h):
                if h and h[-1][0] == "stop":
                    ids = problem.support(h)
                    return sum(problem.worlds[i].mass * problem.reward(h, problem.worlds[i]) for i in ids) / sum(problem.worlds[i].mass for i in ids)
                kind = schedule[len(h)]
                legal = [a for a in problem.legal(h) if a.split(":")[0] == kind]
                feasible = []
                for action in legal:
                    branches = [(p, visit(n)) for p, n in problem.branches(h, action)]
                    # Reject this content choice if any positive-mass continuation
                    # is infeasible; other observable content choices remain valid.
                    if all(v is not None for _, v in branches):
                        feasible.append(-problem.cost(action) + sum(p * v for p, v in branches))
                return max(feasible) if feasible else None

            value = visit(())
            if value is not None and value > best["value"]:
                best = {"value": value, "schedule": schedule}
    return best


def risk_crosscheck(problem, gamma=2.0):
    """Feed the public-history DAG to the inherited CE oracle; independently replay."""
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.oracle import Branch, solve_risk_dp

    nodes, histories = {}, {}

    def build(h):
        name = repr(h)
        if name in nodes:
            return name
        nodes[name], histories[name] = {}, h
        for a in problem.legal(h):
            branches = []
            if a == "stop":
                ids = problem.support(h)
                total = sum(problem.worlds[i].mass for i in ids)
                for i in ids:
                    w = problem.worlds[i]
                    branches.append(Branch(float(w.mass / total), terminal_utility=float(problem.reward(h + ((a, "delivered"),), w))))
            else:
                for p, n in problem.branches(h, a):
                    if problem.legal(n):
                        branches.append(Branch(float(p), float(problem.cost(a)), next_state=build(n)))
                    else:
                        branches.append(Branch(float(p), float(problem.cost(a)), terminal_utility=0.0))
            nodes[name][a] = tuple(branches)
        return name

    root = build(())
    result = solve_risk_dp(nodes, root, gamma)
    paths = replay(problem, lambda h: result["policy"][repr(h)])["paths"]
    log_terms = [math.log(float(p["mass"])) - gamma * float(p["return"]) for p in paths]
    peak = max(log_terms)
    direct = -(peak + math.log(math.fsum(math.exp(x - peak) for x in log_terms))) / gamma
    return {"gamma": gamma, "dp_ce": result["value"], "replayed_ce": direct,
            "absolute_error": abs(result["value"] - direct), "public_nodes": len(nodes)}


def xor_problem(horizon=5, budget=F(1)):
    worlds = tuple(World(F(1, 4), a ^ b, (("sense_a", str(a)), ("sense_b", str(b))))
                   for a, b in product((0, 1), repeat=2))
    return Problem(worlds, (("sense_a", F(1, 10), None), ("sense_b", F(1, 10), None)), horizon, budget)


def adaptive_problem(horizon=5, budget=F(1)):
    worlds = tuple(World(F(1, 4), z, (("sense", str(z) if easy else "?"), ("zoom", str(z))))
                   for easy, z in product((True, False), (0, 1)))
    return Problem(worlds, (("sense", F(1, 10), None), ("zoom", F(1, 5), "sense")), horizon, budget)


def report():
    wall, cpu = time.perf_counter(), time.process_time()
    panels = []
    for name, factory in (("xor_complementarity", xor_problem), ("conditional_zoom", adaptive_problem)):
        for horizon in (3, 4, 5):
            problem = factory(horizon)
            dp, enumeration = solve(problem), brute_force(problem)
            panels.append({"problem": name, "horizon": horizon, "online_dp": dp["value"],
                           "policy_replay": replay(problem, public_policy(problem))["value"],
                           "independent_tree_enumeration": enumeration,
                           "best_fixed": best_fixed(problem),
                           "one_sense_receding": replay(problem, public_policy(problem, 1))["value"],
                           "clairvoyant_upper": clairvoyant(problem),
                           "inherited_gamma2": risk_crosscheck(problem)})
    return {"scope": "exact finite research models; no empirical learning or production qualification",
            "objective": "risk_neutral expected utility minus every executed action cost",
            "panels": panels, "solver_wall_seconds": time.perf_counter() - wall,
            "solver_cpu_seconds": time.process_time() - cpu,
            "solver_compute_excluded_from_mathematical_values": True}


if __name__ == "__main__":
    print(json.dumps(report(), default=str, indent=2, sort_keys=True))
