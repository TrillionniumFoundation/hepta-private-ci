"""Causal R15 one-action owner with an explicit feature-provider argument."""

import time

import numpy as np

from ...addressed_decision_r15_20261101.execution import price
from ...addressed_decision_r15_20261101.planner import BeliefMemory, Planner
from .features import actual_features


def execute(law, episode, learned, feature_provider=actual_features):
    """Only owner execution sees targets; provider sees belief and public prices.

    Exactly the frozen R15 capability: initial STOP, READ then STOP, or REFRESH
    then STOP. No global function replacement, horizon extension or retraining.
    """
    started = time.process_time()
    kind = learned["feature_kind"]
    weights = np.asarray(learned["weights"])
    memory = BeliefMemory(law, episode.initial_values)
    records, feature_cpu = [], 0.
    for query, key in enumerate(episode.query_keys):
        key, dt = int(key), float(episode.dts[query])
        if abs(memory.clock - episode.starts[query]) > 1e-10:
            raise RuntimeError("Owner and memory clocks differ")
        events = episode.events_at(query)
        for event in events:
            if event["kind"] == "WRITE":
                memory.write(int(event["key"]), int(event["value"]))
            elif event["kind"] != "DISTRACTOR":
                raise ValueError("Unknown typed public event")
        scale = price(episode.seed, query)
        planner = Planner(law, dt, .025 * scale, .07 * scale)
        checkpoint = memory.checkpoint()
        before = time.process_time()
        vector = feature_provider(law, memory.beliefs[key], dt, 3,
                                  planner.read_cost, planner.refresh_cost, kind)
        feature_seconds = time.process_time() - before
        feature_cpu += feature_seconds
        gains = vector @ weights
        action = ("STOP", "READ", "REFRESH")[int(np.argmax(np.r_[0., gains]))]
        observations, completed, fee = [], 0, 0.
        if action != "STOP":
            completed = 2 if action == "REFRESH" else 1
            memory.advance(completed * dt)
            time_at = float(episode.starts[query] + completed * dt)
            token = episode.observe(key, time_at, action.lower(), query, completed)
            memory.observe(key, token, action.lower())
            fee = .003 * completed * dt + (planner.read_cost if action == "READ" else planner.refresh_cost)
            observations.append(dict(action=action, step=completed, token=token, time=time_at))
        answer = int(planner.answer(memory.beliefs[key], 3 - completed))
        memory.advance((3 - completed) * dt)
        # Hidden target is requested only after the action and answer commit.
        target = int(episode.target(key, float(episode.deadlines[query])))
        reward = int(answer == target)
        records.append(dict(query=query, key=key, dt=dt, deadline=float(episode.deadlines[query]),
                            price_scale=scale, events=events, actions=observations,
                            answer=answer, target=target, reward=reward, fee=fee,
                            utility=reward - fee, submitted_after=completed * dt,
                            checkpoint_sha256=memory.checkpoint()["sha256"],
                            prefix_checkpoint=checkpoint, features=vector.tolist(), gains=gains.tolist(),
                            feature_cpu_seconds=feature_seconds))
    return dict(seed=episode.seed, world=episode.fingerprint, feature_kind=kind,
                utility=float(np.mean([row["utility"] for row in records])),
                reward=float(np.mean([row["reward"] for row in records])),
                fee=float(np.mean([row["fee"] for row in records])),
                reads=sum(action["action"] == "READ" for row in records for action in row["actions"]),
                refreshes=sum(action["action"] == "REFRESH" for row in records for action in row["actions"]),
                cpu_seconds=time.process_time() - started,
                feature_cpu_seconds=feature_cpu, queries=records,
                operation_counts=dict(feature_calls=len(records),
                                      stop_value_calls=len(records) if kind in ("stop_value", "value_risk") else 0,
                                      first_hit_calls=len(records) if kind == "value_risk" else 0))
