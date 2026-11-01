"""Causal addressed owner execution, fixed-deadline rewards and policy learning."""

import hashlib
import time

import numpy as np

from .planner import BeliefMemory, Planner, features


PATTERNS = {"stop": (), "read": ("READ",), "refresh": ("REFRESH",),
            "two_read": ("READ", "READ"), "wait_read": ("WAIT", "READ"),
            "read_refresh": ("READ", "REFRESH"), "wait_refresh": ("WAIT", "REFRESH"),
            "wait_wait_read": ("WAIT", "WAIT", "READ"),
            "wait_read_read": ("WAIT", "READ", "READ"),
            "read_wait_read": ("READ", "WAIT", "READ"),
            "three_read": ("READ", "READ", "READ"), "refresh_read": ("REFRESH", "READ")}
FEATURE_SETS = {"state_confidence": list(range(8)), "stop_value": list(range(9)),
                "value_risk": list(range(10)), "ordinary_dual": list(range(10))}


def price(seed, query):
    digest = hashlib.sha256(f"r15-price:{seed}:{query}".encode()).digest()
    return (.5, 1., 2., 4.)[digest[0] % 4]


def feature_view(x, kind):
    result = np.asarray(x)[..., FEATURE_SETS[kind]].copy()
    if kind == "ordinary_dual":
        # Equal count to value+risk; the two added channels are ordinary
        # nonlinear transforms of public confidence/phase, not extra data.
        result[..., 8] = result[..., 2] ** 2
        result[..., 9] = 1 / (1 + np.exp(-8 * (result[..., 1] - .5)))
    return result


def run_episode(law, episode, policy="value", pattern="read", projection="full",
                learned=None, method="expm", capture_states=False):
    """Only this owner sees the episode. Policies receive beliefs and prices."""
    started = time.process_time()
    memory = BeliefMemory(law, episode.initial_values, projection, method)
    records, states = [], []
    calls = 0
    for query, key in enumerate(episode.query_keys):
        key, dt = int(key), float(episode.dts[query])
        events = episode.events_at(query)
        if abs(memory.clock - episode.starts[query]) > 1e-10:
            raise RuntimeError("Owner and memory clocks differ")
        for event in events:
            if event["kind"] == "WRITE":
                memory.write(int(event["key"]), int(event["value"]))
            elif event["kind"] != "DISTRACTOR":
                raise ValueError("Unknown typed public event")
        scale = price(episode.seed, query)
        planner = Planner(law, dt, .025 * scale, .07 * scale,
                          projection=projection, method=method)
        completed, fee, observations = 0, 0., []
        sequence = PATTERNS[pattern]
        if capture_states:
            states.append(memory.checkpoint())
        while True:
            remaining = 3 - completed
            if remaining == 0:
                action = "STOP"
            elif policy == "value":
                action = planner.choose(memory.beliefs[key], remaining)
            elif policy == "fixed":
                action = sequence[len(observations)] if len(observations) < len(sequence) else "STOP"
            elif policy == "learned":
                if completed:
                    action = "STOP"
                else:
                    x = features(law, memory.beliefs[key], dt, remaining,
                                 planner.read_cost, planner.refresh_cost)
                    row = feature_view(x, learned["feature_kind"])
                    gains = row @ np.asarray(learned["weights"])
                    action = ("STOP", "READ", "REFRESH")[int(np.argmax(np.r_[0., gains]))]
            else:
                raise ValueError("Unknown policy")
            if action == "REFRESH" and remaining < 2:
                action = "STOP"
            if action == "STOP":
                answer = planner.answer(memory.beliefs[key], remaining)
                break
            slots = 2 if action == "REFRESH" else 1
            memory.advance(slots * dt)
            completed += slots
            fee += .003 * slots * dt
            token = None
            if action in ("READ", "REFRESH"):
                quality = action.lower()
                token = episode.observe(key, float(episode.starts[query] + completed * dt),
                                        quality, query, completed)
                memory.observe(key, token, quality)
                fee += planner.read_cost if action == "READ" else planner.refresh_cost
            observations.append(dict(action=action, step=completed, token=token,
                                     time=float(episode.starts[query] + completed * dt)))
        # Submit before asking the owner for its hidden target; padding carries
        # all four memories to the fixed deadline and has no new observation.
        submitted = int(answer)
        memory.advance((3 - completed) * dt)
        target = int(episode.target(key, float(episode.deadlines[query])))
        correct = int(submitted == target)
        records.append(dict(query=query, key=key, dt=dt, deadline=float(episode.deadlines[query]),
                            price_scale=scale, events=events, actions=observations,
                            answer=submitted, target=target, reward=correct, fee=fee,
                            utility=correct - fee, submitted_after=completed * dt,
                            checkpoint_sha256=memory.checkpoint()["sha256"]))
        calls += planner.belief_evaluations
    return dict(seed=episode.seed, world=episode.fingerprint, policy=policy,
                pattern=pattern, projection=projection, method=method,
                utility=float(np.mean([r["utility"] for r in records])),
                reward=float(np.mean([r["reward"] for r in records])),
                fee=float(np.mean([r["fee"] for r in records])),
                all_queries_correct=bool(all(r["reward"] for r in records)),
                reads=sum(a["action"] == "READ" for r in records for a in r["actions"]),
                refreshes=sum(a["action"] == "REFRESH" for r in records for a in r["actions"]),
                waits=sum(a["action"] == "WAIT" for r in records for a in r["actions"]),
                belief_evaluations=calls, state_bytes=int(memory.beliefs.nbytes),
                cpu_seconds=time.process_time() - started, queries=records,
                states=states if capture_states else None)


def learn_controllers(law, episodes):
    """Fit on actual paired one-action continuations, never model Q-star labels.

    The prefix policy is fixed STOP. Targets execute a READ or REFRESH then
    submit at the same future target time. No trajectory label is an actor
    input. These controllers take at most one observation; their scope differs
    from the primary three-slot value controller.
    """
    started = time.process_time()
    rows, targets, provenance = [], [], []
    for episode in episodes:
        prefix = run_episode(law, episode, policy="fixed", pattern="stop", capture_states=True)
        for query, checkpoint in enumerate(prefix["states"]):
            key, dt = int(episode.query_keys[query]), float(episode.dts[query])
            memory = BeliefMemory.restore(law, checkpoint)
            scale = price(episode.seed, query)
            planner = Planner(law, dt, .025 * scale, .07 * scale)
            target = episode.target(key, float(episode.deadlines[query]))
            stop_return = float(planner.answer(memory.beliefs[key], 3) == target)
            gains = []
            for quality, slots, fee in (("read", 1, planner.read_cost),
                                        ("refresh", 2, planner.refresh_cost)):
                successor = BeliefMemory.restore(law, checkpoint)
                successor.advance(slots * dt)
                token = episode.observe(key, float(episode.starts[query] + slots * dt),
                                        quality, query, slots)
                successor.observe(key, token, quality)
                answer = planner.answer(successor.beliefs[key], 3 - slots)
                gains.append(float(answer == target) - fee - .003 * slots * dt - stop_return)
            rows.append(features(law, memory.beliefs[key], dt, 3,
                                 planner.read_cost, planner.refresh_cost))
            targets.append(gains)
            provenance.append(dict(episode=episode.seed, query=query, world=episode.fingerprint,
                                   stop_return=stop_return, actual_gains=gains))
    x, y = np.asarray(rows), np.asarray(targets)
    fitted = {}
    for kind in FEATURE_SETS:
        design = feature_view(x, kind)
        penalty = np.eye(design.shape[1]) * .1
        penalty[0, 0] = 1e-10
        weights = np.linalg.solve(design.T @ design + penalty, design.T @ y)
        fitted[kind] = dict(feature_kind=kind, weights=weights.tolist(), ridge=.1,
                            training_rows=len(rows), target="realized READ/REFRESH then STOP gain")
    return dict(models=fitted, features=x.tolist(), targets=y.tolist(), provenance=provenance,
                cpu_seconds=time.process_time() - started)
