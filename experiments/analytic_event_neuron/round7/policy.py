"""Causal deployed policies sharing exactly the learned transition kernels."""

import hashlib
import json
import struct
import time

import numpy as np
import torch

from ..analytic import quantize_simplex
from . import oracle
from .task import ACTIONS, features, legal_actions


def keyed_uniform(seed, step, channel):
    key = f"round7/policy/v1/{seed}/{step}/{channel}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2**64


class Policy:
    """Only public State enters act; latent draws never expose private evidence."""

    def __init__(self, model=None, *, head=1, deployment="mean", seed=0, oracle_kind=None):
        self.model, self.head, self.deployment = model, head, deployment
        self.seed, self.oracle_kind = int(seed), oracle_kind
        self.mass = model.initial() if model is not None else None
        self.calls = 0

    def snapshot(self):
        return {"schema": "round7-policy-state-v1", "calls": self.calls,
                "seed": self.seed, "head": self.head, "deployment": self.deployment,
                "mass": None if self.mass is None else self.mass[0].tolist()}

    def restore(self, snapshot):
        if (snapshot["seed"], snapshot["head"], snapshot["deployment"]) != (
                self.seed, self.head, self.deployment):
            raise ValueError("restore policy configuration mismatch")
        self.calls = snapshot["calls"]
        if snapshot["mass"] is not None:
            mass = torch.tensor([snapshot["mass"]], dtype=torch.float64)
            if mass.shape != self.mass.shape or abs(float(mass.sum()) - 1) > 1e-9 or float(mass.min()) < -1e-12:
                raise ValueError("invalid restored mass")
            self.mass = mass

    @torch.no_grad()
    def act(self, state):
        started = time.perf_counter_ns()
        allowed = legal_actions(state)
        if self.oracle_kind:
            values = (oracle.action_values(state) if self.oracle_kind == "optimal"
                      else oracle.myopic_action_values(state))
            action = max(allowed, key=values.get)
            self.calls += 1
            return action, {"q": [values[a] for a in ACTIONS], "event_count": 0.0,
                            "kernel_ns": 0, "prediction_ns": time.perf_counter_ns() - started,
                            "state_bytes": 0, "wire_bytes": len(action.encode()),
                            "event_semantics": "no internal cell"}
        x = torch.from_numpy(features(state)[None, :])
        kernel_start = time.perf_counter_ns()
        previous = self.mass
        next_mass, expected_events, content = self.model.advance(previous, x)
        kernel_ns = time.perf_counter_ns() - kernel_start
        if (not torch.isfinite(next_mass).all() or float(next_mass.min()) < -1e-12
                or abs(float(next_mass.sum()) - 1) > 1e-9):
            raise FloatingPointError("invalid deployed transition mass")
        count = float(expected_events.sum())
        if self.deployment in ("hard", "hard_soft"):
            probabilities = np.clip(next_mass[0].numpy(), 0, None)
            probabilities /= probabilities.sum()
            old_index = int(previous.argmax(dim=-1))
            index = min(len(probabilities) - 1, int(np.searchsorted(
                probabilities.cumsum(), keyed_uniform(self.seed, self.calls, "latent"), side="right")))
            self.mass = torch.nn.functional.one_hot(torch.tensor([index]), len(probabilities)).double()
            count = float(old_index < self.model.n_grid and index >= self.model.n_grid)
        elif self.deployment == "q24":
            integers = quantize_simplex(next_mass[0].tolist(), bits=24)
            self.mass = torch.from_numpy(integers[None, :]).double() / (1 << 24)
        elif self.deployment == "mean":
            self.mass = next_mass
        else:
            raise ValueError(self.deployment)
        q = self.model.values(self.mass, x, content)[0, self.head]
        legal = torch.tensor([a in allowed for a in ACTIONS])
        selected = q.masked_fill(~legal, -1e9)
        if self.deployment == "hard_soft":
            probabilities = torch.softmax(selected / 0.12, dim=-1).numpy()
            choice = min(len(ACTIONS) - 1, int(np.searchsorted(
                probabilities.cumsum(), keyed_uniform(self.seed, self.calls, "action"), side="right")))
        else:
            choice = int(selected.argmax())
        action = ACTIONS[choice]
        moments = self.model.core.state_features(self.mass)[0].tolist()
        self.calls += 1
        snapshot = self.snapshot()
        state_blob = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        # Measured concrete protocol: amplitude/uncertainty and action go on wire
        # every decision, so physical spike count is NOT a communication saving.
        packet = struct.pack("<I5d", self.calls, *moments, count) + action.encode()
        return action, {"q": q.tolist(), "mass": self.mass[0].tolist(), "moments": moments,
                        "event_count": count, "expected_event_count": float(expected_events.sum()),
                        "kernel_ns": kernel_ns, "prediction_ns": time.perf_counter_ns() - started,
                        "state_bytes": len(state_blob), "wire_bytes": len(packet),
                        "wire_hex": packet.hex(), "state_sha256": hashlib.sha256(state_blob).hexdigest(),
                        "event_semantics": "sampled model-event count" if "hard" in self.deployment
                                           else "finite-law expected model-event count",
                        "wire_semantics": "concrete serialized packet; not yet transported"}


def run_episode(policy, episode, *, start_state=None, first_action=None):
    from .task import initial_state, step
    started_cpu = time.process_time_ns()
    state = start_state or initial_state(episode)
    records, reward, action_cost, event_count = [], 0.0, 0.0, 0.0
    while not state.terminated:
        action, prediction = policy.act(state)
        if first_action is not None:
            action, first_action = first_action, None
        result = step(state, action, episode)
        records.append({"before": state.to_dict(), "prediction": prediction,
                        "requested_action": action, "result": result.to_dict()})
        reward += result.reward
        action_cost += result.cost
        event_count += prediction["event_count"]
        state = result.state
    compute_proxy = 0.0005 * len(records)
    event_proxy = 0.0002 * event_count
    return {"episode_seed": episode.seed, "steps": records, "quality": 1.0 if state.answer == episode.truth else -1.0,
            "task_return": reward, "action_cost": action_cost,
            "registered_return": reward - compute_proxy - event_proxy,
            "compute_proxy_cost": compute_proxy, "event_proxy_cost": event_proxy,
            "event_count": event_count, "decisions": len(records),
            "prediction_ns": sum(r["prediction"]["prediction_ns"] for r in records),
            "process_cpu_ns": time.process_time_ns() - started_cpu,
            "kernel_ns": sum(r["prediction"]["kernel_ns"] for r in records),
            "wire_bytes": sum(r["prediction"]["wire_bytes"] for r in records),
            "state_bytes_max": max(r["prediction"]["state_bytes"] for r in records),
            "guard_fallbacks": sum(r["result"]["info"]["guard_fallback"] for r in records),
            "final_state": state.to_dict()}
