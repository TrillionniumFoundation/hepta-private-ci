"""Resettable joint-control experiment with an explicit external task objective.

The learner receives sampled transition banks. Its tabular critic is the proper
moment-loss minimizer on each frozen empirical conditional law; its actor uses
that model's recursive gradient. This plug-in gradient is NOT claimed unbiased
for the true model. Exact DP on the SAME bank is the strong planning control.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from fractions import Fraction as F
from itertools import product
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import time

from .core import Outcome, evaluate, optimal_policy, policy_gradient, softmax_policy
from .policy_gate import guarded_update, initial_value_gate


@dataclass(frozen=True)
class State:
    belief: F = F(1, 2)
    p: int = 0
    budget: int = 6
    resident: int = 0
    clock: int = 0
    remaining: int = 3
    version: str = "fixed-objective-v1:model-v1"


def build_problem(initial=None):
    """Bounded binary evidence task; p is sensing configuration, not reward.

State contains the public posterior, paid internal configuration, energy,
residency, elapsed clock, horizon and fixed versions. Failed sensing consumes
energy/time. All actions reserve their worst-case energy/duration. STOP delivers
the Bayes class with externally fixed correct=1/wrong=-0.4 score; skip returns 0.
"""
    initial = initial or State()
    if (not isinstance(initial, State) or not isinstance(initial.belief, F)
            or any(type(x) is not int for x in (initial.p, initial.resident,
                initial.budget, initial.clock, initial.remaining))
            or not 0 < initial.belief < 1 or initial.p not in (0, 1)
            or initial.resident not in (0, 1) or not 0 <= initial.budget <= 6
            or not 0 <= initial.clock <= 4 or not 0 <= initial.remaining <= 3
            or initial.version != State().version):
        raise ValueError("Unsupported finite task state")
    nodes, states, names = {}, {}, {}

    def visit(s):
        if s in names:
            return names[s]
        name = f"s{len(names):03d}"
        names[s], states[name] = name, s
        accuracy = float(max(s.belief, 1 - s.belief))
        row = {"STOP": (Outcome(accuracy, reward=1.0), Outcome(1-accuracy, reward=-0.4)),
               "skip": (Outcome(1.0),)}
        nodes[name] = row
        if s.remaining == 0 or s.clock + 2 > 4:
            return name
        for mode, reliability in ((0, F(7, 10)), (1, F(9, 10))):
            energy = 1 + mode + int(mode != s.p)
            if energy > s.budget:
                continue
            adjustment = 0.025 * (mode != s.p)
            load_fee = 0.015 * (mode == 1 and s.resident == 0)
            signal_one = s.belief * reliability + (1-s.belief) * (1-reliability)
            outcomes = [(F(1, 10), s.belief, 2)]  # Explicit failed sensing.
            for signal, mass in ((1, signal_one), (0, 1-signal_one)):
                likelihood = reliability if signal else 1-reliability
                posterior = s.belief * likelihood / mass
                outcomes.append((F(9, 10)*mass, posterior, 1 + mode))
            law = []
            for mass, posterior, duration in outcomes:
                successor = State(posterior, mode, s.budget-energy, mode,
                                  s.clock+duration, s.remaining-1, s.version)
                law.append(Outcome(float(mass), cost=0.015*energy+0.01*duration+load_fee,
                                   adjustment_cost=adjustment, duration=duration,
                                   next_state=visit(successor)))
            row["inspect_fast" if mode == 0 else "inspect_precise"] = tuple(law)
        return name

    root = visit(initial)
    return nodes, root, states


def sample_model(nodes, draws, rng):
    if type(draws) is not int or draws < 1:
        raise ValueError("A positive transition sampling budget is required")
    fitted, misses, observed = {}, 0, {}
    for state, actions in nodes.items():
        fitted[state] = {}
        observed[state] = {}
        for action, law in actions.items():
            counts = Counter(rng.choices(range(len(law)),
                                         weights=[o.probability for o in law], k=draws))
            observed[state][action] = [counts.get(i, 0) for i in range(len(law))]
            misses += len(law) - len(counts)
            fitted[state][action] = tuple(Outcome(count/draws, o.reward, o.cost,
                o.adjustment_cost, o.duration, o.next_state)
                for i, o in enumerate(law) if (count := counts.get(i, 0)))
    return fitted, {"transition_calls": draws * sum(map(len, nodes.values())),
                    "outcome_counts": observed,
                    "unobserved_outcome_atoms": misses}


def schedule_policy(nodes, states, schedule):
    pi = {}
    for name, s in states.items():
        depth = 3 - s.remaining
        choice = schedule[depth] if depth < len(schedule) else "STOP"
        if choice not in nodes[name]:
            choice = "STOP"
        pi[name] = {a: float(a == choice) for a in nodes[name]}
    return pi


def fixed_reference(nodes, root, states, eta, rho):
    schedules = [()] + [x for n in range(1, 4)
                       for x in product(("inspect_fast", "inspect_precise"), repeat=n)]
    entries = [(evaluate(nodes, root, schedule_policy(nodes, states, x), eta, rho)["value"], x)
               for x in schedules]
    value, schedule = max(entries, key=lambda x: x[0])
    return {"value": value, "schedule": schedule, "schedules": len(entries)}


def fit_actor(model, root, seed, eta, rho, steps=120):
    rng = random.Random(seed)
    logits = {s: {a: rng.uniform(-0.1, 0.1) for a in row} for s, row in model.items()}
    history = []
    started = time.perf_counter(), time.process_time()
    for step in range(steps):
        r = policy_gradient(model, root, logits, eta, rho)
        # Q=-log(M)/eta solves exp(v)-M*v for frozen empirical continuation.
        for s, row in logits.items():
            for a in row:
                row[a] += 2.0 * r["gradient"][s][a]
        if step in (0, steps-1):
            history.append({"step": step, "empirical_value_before_update": r["value"]})
    return softmax_policy(model, logits), {"steps": steps, "history": history,
        "wall_seconds": time.perf_counter()-started[0],
        "cpu_seconds": time.process_time()-started[1],
        "critic": "exact_tabular_proper_moment_minimizer_on_frozen_empirical_law",
        "gradient": "empirical_model_plugin_not_unbiased_true_model"}


def run(seeds=(1701, 1702, 1703, 1704), draws=64, steps=120):
    started = time.perf_counter(), time.process_time()
    nodes, root, states = build_problem()
    eta, rho = 2.0, 0.17
    exact_start = time.perf_counter(), time.process_time()
    optimum = optimal_policy(nodes, root, eta, rho)
    exact_cost = {"wall_seconds": time.perf_counter()-exact_start[0],
                  "cpu_seconds": time.process_time()-exact_start[1]}
    baseline = {s: {a: float(a == "skip") for a in row} for s, row in nodes.items()}
    base_eval = evaluate(nodes, root, baseline, eta, rho)
    exact_bounds = {s: {a: (q, q) for a, q in row.items()}
                    for s, row in base_eval["action_values"].items()}
    rows = []
    for seed in seeds:
        sample_start = time.perf_counter(), time.process_time()
        empirical, sampling = sample_model(nodes, draws, random.Random(seed))
        sampling.update(wall_seconds=time.perf_counter()-sample_start[0],
                        cpu_seconds=time.process_time()-sample_start[1])
        pi, training = fit_actor(empirical, root, seed+100000, eta, rho, steps)
        plan_start = time.perf_counter(), time.process_time()
        planner = optimal_policy(empirical, root, eta, rho)
        planning = {"wall_seconds": time.perf_counter()-plan_start[0],
                    "cpu_seconds": time.process_time()-plan_start[1]}
        mean_planner = optimal_policy(empirical, root, eta=1e-8, rho=rho)
        # All exact evaluations are validation instrumentation, unavailable to training.
        true = evaluate(nodes, root, pi, eta, rho)
        empirical_eval = evaluate(empirical, root, pi, eta, rho)
        empirical_planner_true = evaluate(nodes, root, planner["policy"], eta, rho)
        gate = guarded_update(baseline, pi, exact_bounds, root, verification_cost=0.01)
        rows.append({"seed": seed, "sampling": sampling, "training": training,
            "same_bank_dp_cost": planning,
            "actor_empirical_value": empirical_eval["value"], "actor_true_value": true["value"],
            "same_bank_dp_empirical_value": planner["value"],
            "same_bank_dp_true_value": empirical_planner_true["value"],
            "risk_neutral_dp_true_entropic_value": evaluate(nodes, root, mean_planner["policy"], eta, rho)["value"],
            "actor_max_Q_error": max(abs(empirical_eval["action_values"][s][a]-true["action_values"][s][a])
                                     for s in nodes for a in nodes[s]),
            "actor_root_policy": pi[root],
            "oracle_interval_gate": {k: v for k, v in gate.items() if k != "policy"},
            "oracle_initial_value_gate": initial_value_gate((true["value"], true["value"]),
                (base_eval["value"], base_eval["value"]), verification_cost=0.01),
            "gate_true_value": evaluate(nodes, root, gate["policy"], eta, rho)["value"]})
    state_json = {s: {**asdict(v), "belief": str(v.belief)} for s, v in states.items()}
    payload = {"states": state_json,
               "nodes": {s: {a: [asdict(o) for o in law] for a, law in row.items()}
                         for s, row in nodes.items()}}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {"schema": "ndu-jac.finite-reset-study.v1", "eta": eta, "rho": rho,
        "model_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "state_count": len(nodes), "state_action_count": sum(map(len, nodes.values())),
        "draws_per_state_action": draws, "seeds": list(seeds),
        "exact_dp_value": optimum["value"], "exact_dp_cost": exact_cost,
        "best_fixed_schedule": fixed_reference(nodes, root, states, eta, rho),
        "no_update_value": base_eval["value"], "rows": rows,
        "model": payload,
        "scope": "bounded_known_support_simulator; no_neural_or_production_superiority_claim",
        "sampling_cost": "transition counts plus measured CPU/wall; no dollar or deployment amortization",
        "gate_scope": "exact baseline Q intervals supplied by oracle; not learned confidence coverage",
        "wall_seconds": time.perf_counter()-started[0], "cpu_seconds": time.process_time()-started[1]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(run(), sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
