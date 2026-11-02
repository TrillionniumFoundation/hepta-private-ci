"""Reuse one owned query snapshot; keep all six commits and restore checks."""

import time

import numpy as np

from ..addressed_decision_r15_20261101.execution import price
from ..addressed_decision_r15_20261101.planner import BeliefMemory, Planner
from ..planner_fastpath_r18_20261101.planner import BatchedPlanner
from ..planner_r19_20261101.planner import OwnedPlanner
from ..support_retention_r16_20261101.compression import AnchoredPackedMemory, PackedBeliefMemory
from ..support_retention_r16_20261101.execution import AnchoredPlanner
from ..planner_r20_20261101.planner import BatchOwnedPlanner
from ..planner_r20_20261101.persistence import load, persist
from .admission import restore_owned


def execute(law, episode, variant, representation, checkpoint_path, cache=None,
            resume_path=None, stop_after_query=None):
    """Actual owner actions plus one complete atomic commit at every query end.

    Resume reuses completed public action/fee history without repeating actions.
    Hidden past targets are recomputed by the scorer, not restored into belief.
    This trusted local Linux profile does not qualify power loss or networking.
    """
    started, wall = time.process_time(), time.perf_counter()
    memory_type = {"block": PackedBeliefMemory, "anchored": AnchoredPackedMemory}.get(representation, BeliefMemory)
    projection = "block" if representation in ("block", "anchored") else representation
    planner_type = {"baseline": AnchoredPlanner if representation == "anchored" else Planner,
                    "r18": BatchedPlanner, "r19": OwnedPlanner, "r20": BatchOwnedPlanner}[variant]
    records, calls, io_cpu, receipts = [], 0, 0., []
    if resume_path is None:
        memory = memory_type(law, episode.initial_values, projection)
        first_query = 0
    else:
        payload = load(resume_path)
        if (payload["model"] != law.identity or payload["world"] != episode.fingerprint
                or payload["seed"] != episode.seed or payload["representation"] != representation):
            raise ValueError("Checkpoint owner/model/representation mismatch")
        first_query = payload["completed_query"] + 1
        if not 1 <= first_query <= len(episode.query_keys) or len(payload["history"]) != first_query:
            raise ValueError("Invalid completed query history")
        memory = restore_owned(memory_type, law, payload["memory"], expected_projection=projection)
        if abs(memory.clock - float(episode.deadlines[first_query - 1])) > 1e-10:
            raise ValueError("Checkpoint is not at its completed deadline")
        calls, receipts = payload["belief_evaluations"], payload["receipts"]
        for public in payload["history"]:
            q = dict(public)
            q["target"] = int(episode.target(q["key"], q["deadline"]))
            q["reward"] = int(q["answer"] == q["target"])
            q["utility"] = q["reward"] - q["fee"]
            records.append(q)
    for query in range(first_query, len(episode.query_keys)):
        key, dt = int(episode.query_keys[query]), float(episode.dts[query])
        if abs(memory.clock - episode.starts[query]) > 1e-10:
            raise RuntimeError("Owner and memory clocks differ")
        events = episode.events_at(query)
        for event in events:
            if event["kind"] == "WRITE":
                memory.write(int(event["key"]), int(event["value"]))
            elif event["kind"] != "DISTRACTOR":
                raise ValueError("Unknown typed public event")
        scale = price(episode.seed, query)
        kwargs = {} if variant == "baseline" else dict(anchored=representation == "anchored", cache=cache)
        planner = planner_type(law, dt, .025 * scale, .07 * scale, projection=projection, **kwargs)
        completed, fee, actions = 0, 0., []
        while True:
            remaining = 3 - completed
            p = memory.materialize(key) if representation == "anchored" else memory.beliefs[key]
            action = planner.choose(p, remaining) if remaining else "STOP"
            if action == "STOP":
                answer = planner.answer(p, remaining)
                break
            slots = 2 if action == "REFRESH" else 1
            memory.advance(slots * dt)
            completed += slots
            fee += .003 * slots * dt
            token = None
            if action in ("READ", "REFRESH"):
                token = episode.observe(key, float(episode.starts[query] + completed * dt),
                                        action.lower(), query, completed)
                memory.observe(key, token, action.lower())
                fee += planner.read_cost if action == "READ" else planner.refresh_cost
            actions.append(dict(action=action, step=completed, token=token,
                                time=float(episode.starts[query] + completed * dt)))
        memory.advance((3 - completed) * dt)
        target = int(episode.target(key, float(episode.deadlines[query])))
        correct = int(answer == target)
        snapshot = memory.checkpoint()
        records.append(dict(query=query, key=key, dt=dt, deadline=float(episode.deadlines[query]),
                            price_scale=scale, events=events, actions=actions, answer=int(answer),
                            target=target, reward=correct, fee=fee, utility=correct - fee,
                            submitted_after=completed * dt, checkpoint_sha256=snapshot["sha256"]))
        calls += planner.belief_evaluations
        io_start = time.process_time()
        receipt = dict(query=query, memory_sha256=records[-1]["checkpoint_sha256"],
                       file_fsyncs=1, directory_fsyncs=1)
        receipts.append(receipt)
        body = dict(schema="hcsn-r20-query-checkpoint-v1", model=law.identity, seed=episode.seed,
                    world=episode.fingerprint, representation=representation, completed_query=query,
                    memory=snapshot, belief_evaluations=calls, receipts=receipts,
                    history=[{k: v for k, v in row.items() if k not in ("target", "reward", "utility")}
                             for row in records])
        saved = persist(checkpoint_path, body)
        memory = restore_owned(memory_type, law, saved["memory"], expected_projection=projection)
        if memory.checkpoint() != body["memory"]:
            raise RuntimeError("Owned state changed during durable restoration")
        io_cpu += time.process_time() - io_start
        if query == stop_after_query:
            break
    return dict(seed=episode.seed, world=episode.fingerprint, representation=representation,
                utility=float(np.mean([q["utility"] for q in records])),
                reward=float(np.mean([q["reward"] for q in records])),
                fee=float(np.mean([q["fee"] for q in records])), queries=records,
                checkpoint_receipts=receipts, belief_evaluations=calls,
                checkpoint_io_cpu_seconds=io_cpu, cpu_seconds=time.process_time() - started,
                wall_seconds=time.perf_counter() - wall)
