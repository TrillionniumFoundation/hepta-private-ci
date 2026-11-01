"""Matched planning/execution for full, projected and event-anchored memory."""

import json
import os
import time

import numpy as np

from ..addressed_decision_r15_20261101.execution import PATTERNS, price
from ..addressed_decision_r15_20261101.planner import BeliefMemory, Planner
from .compression import AnchoredPackedMemory, PackedBeliefMemory


class AnchoredPlanner(Planner):
    """Project only after information; unobserved elapsed time retains phase shape.

    This is the same finite action tree as R15. Only the timing of the explicitly
    declared compression changes. The full-model STOP forecast is not projected.
    """

    def _values(self, p, remaining):
        p = np.asarray(p, dtype=float).reshape(-1, 40)
        self.belief_evaluations += len(p)
        result = np.full((len(p), 4), -np.inf)
        result[:, 0] = np.max(p @ self.reward_at[remaining], axis=1)
        if not remaining:
            return result
        result[:, 1] = np.max(self._values(p @ self.P[1], remaining - 1), axis=1)
        result[:, 1] -= self.time_price * self.dt
        for column, slots, emission, fee in (
                (2, 1, self.law.E_read, self.read_cost),
                (3, 2, self.law.E_refresh, self.refresh_cost)):
            if slots > remaining:
                continue
            joint = (p @ self.P[slots])[:, None, :] * emission.T[None, :, :]
            likelihood = joint.sum(-1)
            posterior = np.divide(joint, likelihood[..., None], out=np.zeros_like(joint),
                                  where=likelihood[..., None] > 0)
            posterior[likelihood <= 0] = self.law.prior
            posterior = self.law.project(posterior, "block")
            successor = np.max(self._values(posterior.reshape(-1, 40), remaining - slots), axis=1)
            result[:, column] = np.sum(likelihood * successor.reshape(likelihood.shape), axis=1)
            result[:, column] -= fee + slots * self.dt * self.time_price
        return result


def execute(law, episode, policy="value", pattern="stop", representation="full", checkpoint_path=None):
    """Owner-controlled execution; only public beliefs/prices reach the controller.

    A disk checkpoint is taken at a query boundary after the third query, where
    no action is pending. This does not qualify mid-action production recovery.
    """
    started, wall = time.process_time(), time.perf_counter()
    memory_type = {"block": PackedBeliefMemory, "anchored": AnchoredPackedMemory}.get(
        representation, BeliefMemory)
    projection = "block" if representation in ("block", "anchored") else representation
    memory = memory_type(law, episode.initial_values, projection)
    planner_type = AnchoredPlanner if representation == "anchored" else Planner
    records, calls, io_cpu = [], 0, 0.
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
        planner = planner_type(law, dt, .025 * scale, .07 * scale, projection=projection)
        completed, fee, actions = 0, 0., []
        sequence = PATTERNS[pattern]
        while True:
            remaining = 3 - completed
            p = memory.materialize(key) if representation == "anchored" else memory.beliefs[key]
            if not remaining:
                action = "STOP"
            elif policy == "value":
                action = planner.choose(p, remaining)
            elif policy == "fixed":
                action = sequence[len(actions)] if len(actions) < len(sequence) else "STOP"
            else:
                raise ValueError("Unknown policy")
            if action == "REFRESH" and remaining < 2:
                action = "STOP"
            if action == "STOP":
                answer = planner.answer(p, remaining)
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
            actions.append(dict(action=action, step=completed, token=token,
                                time=float(episode.starts[query] + completed * dt)))
        submitted = int(answer)
        memory.advance((3 - completed) * dt)
        target = int(episode.target(key, float(episode.deadlines[query])))
        correct = int(submitted == target)
        records.append(dict(query=query, key=key, dt=dt, deadline=float(episode.deadlines[query]),
                            price_scale=scale, events=events, actions=actions, answer=submitted,
                            target=target, reward=correct, fee=fee, utility=correct - fee,
                            submitted_after=completed * dt,
                            checkpoint_sha256=memory.checkpoint()["sha256"]))
        calls += planner.belief_evaluations
        if query == 2 and checkpoint_path is not None:
            io_start = time.process_time()
            snapshot = memory.checkpoint()
            with checkpoint_path.open("w") as stream:
                json.dump(snapshot, stream, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            restored = memory_type.restore(law, json.loads(checkpoint_path.read_text()))
            if restored.checkpoint() != snapshot:
                raise RuntimeError("Checkpoint roundtrip changed owned state")
            memory = restored
            io_cpu += time.process_time() - io_start
    state_bytes = 1280
    if representation in ("block", "anchored"):
        state_bytes = memory.packed.nbytes + (memory.anchor_times.nbytes if representation == "anchored" else 0)
    return dict(seed=episode.seed, world=episode.fingerprint, representation=representation,
                utility=float(np.mean([r["utility"] for r in records])),
                reward=float(np.mean([r["reward"] for r in records])),
                fee=float(np.mean([r["fee"] for r in records])), queries=records,
                state_numeric_bytes=int(state_bytes + 8), temporary_belief_bytes=1280,
                checkpoint_io_cpu_seconds=io_cpu, belief_evaluations=calls,
                cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall)
