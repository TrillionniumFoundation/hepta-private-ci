"""Finite development experiment: reachable joint beliefs and paid continuations.

The relation observation is a real emission from an owner sampled at p0.
All registered scenarios and forced first actions are retained. A public
context plus one relation bit reconstructs the full initial belief exactly;
this experiment cannot establish that forty stored probabilities are needed.
"""

import argparse
import hashlib
import itertools
import json
import math
import time
from pathlib import Path

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import ACTIONS, Planner


HERE = Path(__file__).resolve().parent
SOURCE_FILES = (Path(__file__), HERE.parent / "addressed_decision_r15_20261101/law.py",
                HERE.parent / "addressed_decision_r15_20261101/planner.py")
SPEC = dict(schema="hcsn.reachable-joint.development.v1", seed=2026110181,
            phase_pairs=[[0, 8], [7, 9], [2, 5]], class_pairs=[[0, 1], [1, 3]],
            marginal_pairs=[[.3, .7], [.7, .85]], durations=[.3, .8],
            price_multipliers=[.5, 4.], remaining_slots=2, worlds_per_scenario=512,
            transport_fraction=.9, uniform_background=1e-6,
            theta=[.30, .018], read_fee=.025, refresh_fee=.07, time_price=.003,
            owner_transition="independent positive uniformization, tail < 2e-15",
            interpretation="development mechanism evidence, no confirmation or production gate",
            selection="all 48 scenarios, both relation symbols, all four forced first actions",
            reference="public construction plus one relation bit; same-Q ordinary HMM",
            sampling="shared owner trajectory and token opportunity across every policy",
            unresolved="multi-relation histories, learned addressing, general low-rank closure, full cost advantage")


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identities():
    return {str(path.relative_to(HERE.parent)): digest(path) for path in SOURCE_FILES}


def transport(phases, classes, masses):
    base = np.outer([masses[0], 1-masses[0]], [masses[1], 1-masses[1]])
    p0 = np.full((10, 4), SPEC["uniform_background"] / 40)
    p0[np.ix_(phases, classes)] += (1-SPEC["uniform_background"]) * base
    delta = np.zeros_like(p0)
    delta[np.ix_(phases, classes)] = ((1-SPEC["uniform_background"]) *
        SPEC["transport_fraction"] * base.min() * np.array([[1., -1.], [-1., 1.]]))
    pair = np.stack([(p0+delta).ravel(), (p0-delta).ravel()])
    emission = pair.T / (2*p0.ravel()[:, None])
    return p0.ravel(), delta.ravel(), pair, emission


def uniformization(q, duration):
    rate = float(max(-np.diag(q)))
    jump = np.eye(len(q)) + q/rate
    if jump.min() < 0 or not np.allclose(jump.sum(1), 1, rtol=0, atol=2e-13):
        raise AssertionError("Invalid uniformization jump matrix")
    mean, weight = rate*duration, math.exp(-rate*duration)
    power, result = np.eye(len(q)), weight*np.eye(len(q))
    for k in range(1, 10000):
        power = power @ jump
        weight *= mean/k
        result += weight*power
        if k > mean and weight*(mean/(k+1))/(1-mean/(k+2)) < 2e-15:
            return result
    raise AssertionError("Uniformization tail did not converge")


def policy_tree(planner, belief, remaining, forced=None):
    action = forced or planner.choose(belief, remaining)
    if action == "STOP":
        return dict(action=action, answer=planner.answer(belief, remaining), remaining=remaining)
    slots = 2 if action == "REFRESH" else 1
    before = planner.law.project(belief @ planner.P[slots], planner.projection)
    fee = slots*planner.dt*planner.time_price + (
        planner.read_cost if action == "READ" else planner.refresh_cost if action == "REFRESH" else 0.)
    if action == "WAIT":
        children = [policy_tree(planner, before, remaining-slots)]
    else:
        emission = planner.law.E_read if action == "READ" else planner.law.E_refresh
        children = []
        for column in emission.T:
            posterior = before*column
            mass = float(posterior.sum())
            if mass <= 0:
                raise AssertionError("Registered positive-support profile lost an observation")
            children.append(policy_tree(planner, planner.law.project(
                posterior/mass, planner.projection), remaining-slots))
    return dict(action=action, slots=slots, fee=fee, children=children)


def value_vector(tree, law, transitions):
    """Evaluate a fixed tree under true owner dynamics, not its forecast belief."""
    if tree["action"] == "STOP":
        return transitions[tree["remaining"]] @ law.reward[:, tree["answer"]]
    successor = [value_vector(child, law, transitions) for child in tree["children"]]
    if tree["action"] == "WAIT":
        after = successor[0]
    else:
        emission = law.E_read if tree["action"] == "READ" else law.E_refresh
        after = np.sum(emission * np.stack(successor, axis=1), axis=1)
    return transitions[tree["slots"]] @ after - tree["fee"]


def sample_rows(probabilities, uniforms):
    cumulative = np.cumsum(probabilities, axis=1)
    if np.max(np.abs(cumulative[:, -1]-1)) > 2e-12 or probabilities.min() < 0:
        raise AssertionError("Owner sampling needs stochastic rows")
    # Set only the final cumulative endpoint, within the checked roundoff bound.
    cumulative[:, -1] = 1.
    return (uniforms[:, None] >= cumulative).sum(1)


def execute(tree, rows, worlds, answers, fees, clock=0, spent=0.):
    """Replay a fixed causal tree; only the final scorer accesses target content."""
    if tree["action"] == "STOP":
        answers[rows], fees[rows] = tree["answer"], spent
        return
    clock, spent = clock+tree["slots"], spent+tree["fee"]
    if tree["action"] == "WAIT":
        execute(tree["children"][0], rows, worlds, answers, fees, clock, spent)
    else:
        tokens = worlds[tree["action"].lower()][rows, clock-1]
        for token, child in enumerate(tree["children"]):
            execute(child, rows[tokens == token], worlds, answers, fees, clock, spent)


def run(protocol, out):
    frozen = json.loads(protocol.read_text())
    if frozen["spec"] != SPEC or frozen["source_sha256"] != identities():
        raise ValueError("Frozen protocol/source mismatch")
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    law = Law(SPEC["theta"])
    hmm = Law.from_export(law.export())
    configurations = itertools.product(SPEC["phase_pairs"], SPEC["class_pairs"],
        SPEC["marginal_pairs"], SPEC["durations"], SPEC["price_multipliers"])
    records, raw_files, max_errors = [], [], dict(bayes=0., marginals=0., transition=0., planner_value=0.)
    for index, (phases, classes, masses, dt, price) in enumerate(configurations):
        p0, delta, pair, emission = transport(phases, classes, masses)
        symbol_mass = p0 @ emission
        bayes = (p0[:, None]*emission/symbol_mass).T
        max_errors["bayes"] = max(max_errors["bayes"], float(abs(bayes-pair).max()))
        joint = pair.reshape(2, 10, 4)
        max_errors["marginals"] = max(max_errors["marginals"],
            float(abs(joint[0].sum(0)-joint[1].sum(0)).max()),
            float(abs(joint[0].sum(1)-joint[1].sum(1)).max()))
        if min(pair.min(), emission.min()) < 0 or not np.allclose(symbol_mass, .5, atol=1e-14):
            raise AssertionError("Invalid reachable joint construction")
        step = uniformization(law.Q, dt)
        transitions = {0: np.eye(40), 1: step, 2: step @ step}
        max_errors["transition"] = max(max_errors["transition"],
            max(float(abs(transitions[h]-law.transition(h*dt)).max()) for h in range(3)))
        rng = np.random.default_rng(np.random.SeedSequence([SPEC["seed"], index]))
        count = SPEC["worlds_per_scenario"]
        states = np.zeros((count, 3), dtype=int)
        states[:, 0] = rng.choice(40, count, p=p0)
        symbols = (rng.random(count) >= emission[states[:, 0], 0]).astype(int)
        for clock in (1, 2):
            states[:, clock] = sample_rows(step[states[:, clock-1]], rng.random(count))
        worlds = {kind: np.stack([sample_rows(matrix[states[:, t]], rng.random(count))
            for t in (1, 2)], axis=1) for kind, matrix in
            (("read", law.E_read), ("refresh", law.E_refresh))}
        raw = dict(scenario=index, states=states.tolist(), symbols=symbols.tolist(),
                   observations={k: v.tolist() for k, v in worlds.items()}, policies={})
        planners = {mode: Planner(law, dt, read_cost=SPEC["read_fee"]*price,
            refresh_cost=SPEC["refresh_fee"]*price, projection=mode) for mode in ("full", "factorized")}
        ordinary = Planner(hmm, dt, read_cost=SPEC["read_fee"]*price,
                           refresh_cost=SPEC["refresh_fee"]*price)
        record = dict(scenario=index, phases=phases, classes=classes, masses=masses,
                      dt=dt, price_multiplier=price, pair=pair.tolist(), prefixes=[])
        for symbol, true in enumerate(bayes):
            prefix = dict(symbol=symbol, probability=float(symbol_mass[symbol]), policies={})
            # Public construction/emission + the observed bit suffice. Match
            # Bayes operation order, avoiding a spurious two-ULP comparison.
            reference = p0 * emission[:, symbol] / symbol_mass[symbol]
            if not np.array_equal(reference, true):
                raise AssertionError("Public-context plus relation-bit reference mismatch")
            oracle_values = planners["full"].values(true, 2)
            best = max(oracle_values, key=oracle_values.get)
            for mode, planner in planners.items():
                belief = law.project(true, mode)
                selected = planner.choose(belief, 2)
                by_action = {}
                for forced in ACTIONS:
                    tree = policy_tree(planner, belief, 2, forced)
                    expected = float(true @ value_vector(tree, law, transitions))
                    if mode == "full":
                        max_errors["planner_value"] = max(max_errors["planner_value"], abs(expected-oracle_values[forced]))
                        if tree != policy_tree(ordinary, true, 2, forced) or tree != policy_tree(ordinary, reference, 2, forced):
                            raise AssertionError("Same-Q HMM or relation-bit policy differs")
                    key = mode+"_"+forced
                    if key not in raw["policies"]:
                        raw["policies"][key] = dict(answers=np.full(count, -1), fees=np.zeros(count))
                    output = raw["policies"][key]
                    rows = np.flatnonzero(symbols == symbol)
                    execute(tree, rows, worlds, output["answers"], output["fees"])
                    rewards = (output["answers"][rows] == states[rows, -1] % 4).astype(float)-output["fees"][rows]
                    by_action[forced] = dict(expected_utility=expected,
                        regret=max(oracle_values.values())-expected, samples=len(rows),
                        sampled_utility=float(rewards.mean()) if len(rows) else None, tree=tree)
                prefix["policies"][mode] = dict(selected_action=selected,
                    expected_utility=by_action[selected]["expected_utility"], actions=by_action)
            prefix["oracle_action"] = best
            prefix["full_minus_factorized"] = (prefix["policies"]["full"]["expected_utility"]-
                                                    prefix["policies"]["factorized"]["expected_utility"])
            rows = np.flatnonzero(symbols == symbol)
            utilities = {key: (value["answers"][rows] == states[rows, -1] % 4).astype(float)-value["fees"][rows]
                         for key, value in raw["policies"].items()}
            for mode in planners:
                for forced in ACTIONS:
                    prefix["policies"][mode]["actions"][forced]["paired_sampled_regret"] = float(
                        np.mean(utilities["full_"+best]-utilities[mode+"_"+forced])) if len(rows) else None
            delta_sample = utilities["full_"+best]-utilities["factorized_"+prefix["policies"]["factorized"]["selected_action"]]
            prefix["paired_sampled_full_minus_factorized"] = dict(mean=float(delta_sample.mean()) if len(rows) else None,
                standard_error=float(delta_sample.std(ddof=1)/math.sqrt(len(rows))) if len(rows) > 1 else None)
            record["prefixes"].append(prefix)
        raw["policies"] = {k: {name: values.tolist() for name, values in v.items()}
                           for k, v in raw["policies"].items()}
        target = out.parent / f"{out.stem}_scenario_{index:03d}.json"
        raw["evaluation"] = record
        dump(target, raw)
        raw_files.append(dict(path=target.name, sha256=digest(target), bytes=target.stat().st_size))
        for prefix in record["prefixes"]:
            for policy in prefix["policies"].values():
                for action in policy["actions"].values():
                    action.pop("tree")
        records.append(record)
    if max(max_errors.values()) > 3e-11 or len(records) != 48:
        raise AssertionError("Finite validity contract failed")
    differences = [p["full_minus_factorized"] for row in records for p in row["prefixes"]]
    summary = dict(schema=SPEC["schema"], protocol_sha256=digest(protocol), source_sha256=identities(),
        validity_passed=True, scenarios=len(records), prefixes=len(differences),
        owner_worlds=len(records)*SPEC["worlds_per_scenario"], errors=max_errors,
        full_minus_factorized_mean=float(np.mean(differences)),
        full_minus_factorized_min=float(min(differences)), full_minus_factorized_max=float(max(differences)),
        positive_above_1e_6=sum(x > 1e-6 for x in differences),
        same_q_hmm_and_public_context_relation_bit_identical=True,
        full_distribution_necessity_established=False, hx_exclusive_gain_established=False,
        confirmation=False, cost=dict(cpu_seconds=time.process_time()-started_cpu,
            wall_seconds=time.perf_counter()-started_wall, startup_included=False),
        raw_files=raw_files, records=records)
    dump(out, summary)
    return {k: v for k, v in summary.items() if k not in ("records", "raw_files")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--protocol", type=Path, default=HERE / "results/reachable_protocol.json")
    parser.add_argument("--output", type=Path, default=HERE / "results/reachable_results.json")
    args = parser.parse_args()
    if args.freeze:
        dump(args.protocol, dict(spec=SPEC, source_sha256=identities()))
    else:
        print(json.dumps(run(args.protocol, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
