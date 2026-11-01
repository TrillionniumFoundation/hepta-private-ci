"""Frozen-budget action witnesses for joint-state information.

This is a development diagnostic, not a significance test or confirmation
selection rule. A synthetic joint distribution need not be a reachable filter
posterior. The separate history probe makes only its full posterior reachable;
its instantaneous factorized intervention need not itself be reachable.
"""

import argparse
import itertools
import json
import time
from contextlib import nullcontext
from pathlib import Path

import numpy as np

from .law import Law
from .planner import BeliefMemory, Planner
from .world import make_episode


SYNTHETIC_SEED = 815400
HISTORY_SEED = 815500
SYNTHETIC_PAIRS = 96
HISTORY_EPISODES = 16
DURATIONS = (.25, .50, .75, .35, .65, .95)
PRICES = (.5, 1., 2., 4.)
REMAINING = (1, 2, 3)
MIN_GAP = 1e-6


def paired_joint_beliefs(rng):
    """Opposite transports around one factorized 2-by-2 probability table."""
    active, recovery = int(rng.integers(8)), int(rng.integers(8, 10))
    classes = list(map(int, rng.permutation(4)[:2]))
    phase_mass, class_mass = float(rng.uniform(.15, .85)), float(rng.uniform(.55, .95))
    base = np.outer([phase_mass, 1 - phase_mass], [class_mass, 1 - class_mass])
    amplitude = .98 * float(base.min())
    direction = np.array([[1., -1.], [-1., 1.]])
    pair = []
    for sign in (1, -1):
        joint = np.full((10, 4), 1e-6 / 40)
        joint[np.ix_([active, recovery], classes)] += (1 - 1e-6) * (base + sign * amplitude * direction)
        pair.append(joint.ravel())
    return pair[0], pair[1], dict(active=active, recovery=recovery, classes=classes,
                                  phase_mass=phase_mass, class_mass=class_mass,
                                  transport_amplitude=amplitude)


def _compare(planner, p, q, remaining):
    left, right = planner.values(p, remaining), planner.values(q, remaining)
    best_left = sorted(left, key=left.get, reverse=True)
    best_right = sorted(right, key=right.get, reverse=True)
    gap_left = left[best_left[0]] - left[best_left[1]]
    gap_right = right[best_right[0]] - right[best_right[1]]
    a, b = p.reshape(10, 4), q.reshape(10, 4)
    phase_error = float(np.max(np.abs(a.sum(1) - b.sum(1))))
    content_error = float(np.max(np.abs(a.sum(0) - b.sum(0))))
    if max(phase_error, content_error) > 1e-12:
        raise AssertionError("Probe pair does not have the same two marginals")
    return dict(actions=[best_left[0], best_right[0]], gaps=[gap_left, gap_right],
                q_values=[left, right], phase_marginal_error=phase_error,
                content_marginal_error=content_error,
                different_action=best_left[0] != best_right[0],
                qualifies=best_left[0] != best_right[0] and min(gap_left, gap_right) > MIN_GAP)


def run_probe(synthetic_pairs=SYNTHETIC_PAIRS, history_episodes=HISTORY_EPISODES):
    """Run the frozen default grid; first qualifying witness stops each probe."""
    if synthetic_pairs < 0 or history_episodes < 0:
        raise ValueError("Search budgets must be nonnegative")
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    try:
        from threadpoolctl import threadpool_limits
        limits = threadpool_limits(limits=1)
    except ImportError:
        limits = nullcontext()
    with limits:
        law = Law()
        planners = {}

        def planner(dt, price):
            key = (float(dt), float(price))
            if key not in planners:
                planners[key] = Planner(law, dt, read_cost=.025 * price,
                                        refresh_cost=.07 * price, time_price=.003)
            return planners[key]

        synthetic = dict(found=False, pair_budget=synthetic_pairs,
                         maximum_pair_grid_evaluations=synthetic_pairs * 72,
                         attempted_pair_grid_evaluations=0, generated_pairs=0,
                         witness=None, strongest_nonqualifying=None)
        rng = np.random.default_rng(SYNTHETIC_SEED)
        synthetic_start = time.process_time()
        for pair_index in range(synthetic_pairs):
            p, q, construction = paired_joint_beliefs(rng)
            synthetic["generated_pairs"] += 1
            for remaining, dt, price in itertools.product(REMAINING, DURATIONS, PRICES):
                compared = _compare(planner(dt, price), p, q, remaining)
                synthetic["attempted_pair_grid_evaluations"] += 1
                row = dict(pair_index=pair_index, dt=dt, price=price, remaining=remaining,
                           construction=construction, **compared)
                old = synthetic["strongest_nonqualifying"]
                if old is None or (int(row["different_action"]), min(row["gaps"])) > (
                        int(old["different_action"]), min(old["gaps"])):
                    synthetic["strongest_nonqualifying"] = row
                if compared["qualifies"]:
                    synthetic.update(found=True, witness=dict(beliefs=[p.tolist(), q.tolist()], **row))
                    break
            if synthetic["found"]:
                break
        synthetic["exhausted_without_witness"] = not synthetic["found"]
        synthetic["cpu_seconds"] = time.process_time() - synthetic_start
        synthetic["scope"] = "Synthetic controllability witness; no reachable-posterior claim"

        history = dict(found=False, episode_budget=history_episodes,
                       maximum_pair_grid_evaluations=history_episodes * 6 * 2 * 4,
                       attempted_pair_grid_evaluations=0, generated_episodes=0,
                       owner_observations_consumed=0, witness=None,
                       strongest_nonqualifying=None)
        history_start = time.process_time()
        for index in range(history_episodes):
            domain = "iid" if index % 2 == 0 else "ood"
            world = make_episode(law, HISTORY_SEED + index, domain)
            history["generated_episodes"] += 1
            memory = BeliefMemory(law, world.initial_values)
            public_prefix = [dict(event) for event in world.public_events]
            for query, key in enumerate(world.query_keys):
                key, dt = int(key), float(world.dts[query])
                for event in world.events_at(query):
                    public_prefix.append(dict(event))
                    if event["kind"] == "WRITE":
                        memory.write(event["key"], event["value"])
                for completed in (0, 1):
                    if completed == 1:
                        memory.advance(dt)
                        time_at = float(world.starts[query] + dt)
                        token = world.observe(key, time_at, "read", query, 1)
                        memory.observe(key, token, "read")
                        history["owner_observations_consumed"] += 1
                        public_prefix.append(dict(kind="READ", key=key, token=token, time=time_at))
                    p = memory.beliefs[key].copy()
                    q = law.project(p, "factorized")
                    for price in PRICES:
                        compared = _compare(planner(dt, price), p, q, 3 - completed)
                        history["attempted_pair_grid_evaluations"] += 1
                        row = dict(episode_seed=HISTORY_SEED + index, domain=domain,
                                   query=query, key=key, completed_step=completed,
                                   dt=dt, price=price, remaining=3 - completed, **compared)
                        old = history["strongest_nonqualifying"]
                        if old is None or (int(row["different_action"]), min(row["gaps"])) > (
                                int(old["different_action"]), min(old["gaps"])):
                            history["strongest_nonqualifying"] = row
                        if compared["qualifies"]:
                            history.update(found=True, witness=dict(
                                beliefs=[p.tolist(), q.tolist()], public_prefix=list(public_prefix),
                                world_fingerprint=world.fingerprint, **row))
                            break
                    if history["found"]:
                        break
                if history["found"]:
                    break
                memory.advance(2 * dt)
                token = world.observe(key, float(world.deadlines[query]), "refresh", query, 3)
                memory.observe(key, token, "refresh")
                history["owner_observations_consumed"] += 1
                public_prefix.append(dict(kind="REFRESH", key=key, token=token,
                                          time=float(world.deadlines[query])))
            if history["found"]:
                break
        history["exhausted_without_witness"] = not history["found"]
        history["cpu_seconds"] = time.process_time() - history_start
        history["scope"] = ("Full posterior is reached by the listed raw public history under the true-model "
                            "finite filter. Its instantaneous factorized projection need not be reachable. "
                            "Both receive the same model and costs; this is not a fitted-arm or confirmation result.")
        return dict(schema="hcsn-r15-decision-probe-v1", law_identity=law.identity,
                    specification=dict(synthetic_seed=SYNTHETIC_SEED, history_seed=HISTORY_SEED,
                                       durations=list(DURATIONS), prices=list(PRICES), remaining=list(REMAINING),
                                       min_strict_action_gap=MIN_GAP,
                                       stop_rule="First differing action with both gaps strictly above threshold; else exhaust fixed budget"),
                    synthetic=synthetic, reachable_history=history,
                    cost=dict(cpu_seconds=time.process_time() - start_cpu,
                              wall_seconds=time.perf_counter() - start_wall,
                              planners_constructed=len(planners),
                              planner_calls=sum(item.calls for item in planners.values()),
                              candidate_belief_evaluations=sum(item.belief_evaluations for item in planners.values()),
                              planner_preparation_cpu_seconds=sum(item.preparation_cpu for item in planners.values()),
                              scope="All law/world construction, history generation, propagation, candidate actions and search; imported-library startup excluded"),
                    inference_limit="Existence of a decision-sensitive joint state is not measured gain, general reachability, semantic content, or production admission.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-pairs", type=int, default=SYNTHETIC_PAIRS)
    parser.add_argument("--history-episodes", type=int, default=HISTORY_EPISODES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_probe(args.synthetic_pairs, args.history_episodes)
    encoded = json.dumps(result, indent=2, allow_nan=False)
    if args.output is None:
        print(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")


if __name__ == "__main__":
    main()
