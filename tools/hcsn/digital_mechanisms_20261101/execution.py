"""Actual packet execution and supervised occupancy records for the new study."""
import copy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..digital_read_before_20261031.task import (
    Owner, Oracle, evaluate_terminal, fixed_action, history_features, legal,
    posterior, public_features,
)
from .models import accumulator_features, mechanism_context_key, transition_context


def occupancy_key(state):
    """Coarse observable coverage diagnostic, not proof of distribution support."""
    return (state["tick"], state["budget"], state["broken"], state["pending"] is not None,
            len(state["history"]), state["last_symbol"])


class Runtime:
    """NumPy head with lazy exact Torch finite tables, all preparation charged."""

    def __init__(self, policy):
        self.policy = policy
        self.network = [p.detach().numpy().copy() for p in (
            policy.linear1.weight, policy.linear1.bias, policy.linear2.weight, policy.linear2.bias)]
        self.features, self.transitions = {}, {}
        self.preparation_cpu = 0.
        self.preparation_calls = 0

    def predict(self, public, state, index):
        policy = self.policy
        if policy.drive_mode == "accumulator":
            representation = accumulator_features(state)
        elif policy.cell is None:
            representation = history_features(state)
        else:
            key = (state["last_symbol"], state["last_reliability"])
            if policy.drive_mode == "impulse":
                key = (0., .5)
            if key not in self.features:
                cpu = time.process_time()
                with torch.no_grad():
                    self.features[key] = policy.cell.features(*key, bank=policy.use_bank).numpy().copy()
                self.preparation_cpu += time.process_time() - cpu
                self.preparation_calls += 1
            representation = self.features[key][index]
        x = np.concatenate((public_features(public, state), representation))
        w1, b1, w2, b2 = self.network
        output = w2 @ np.tanh(w1 @ x + b1) + b2
        logit = float(output[-1])
        belief = float(1 / (1 + np.exp(-np.clip(logit, -700, 700))))
        q = (output[:6] if policy.terminal_mode == "free" else
             np.asarray([0., *output[:3], 1 - 2 * belief, 2 * belief - 1]))
        return dict(q=q.tolist(), belief=belief, belief_logit=logit)

    def advance(self, context, index, rng):
        if self.policy.cell is None:
            return 0, dict(event=False, recovery=False, sampled=False)
        key = mechanism_context_key(context)
        if key not in self.transitions:
            cpu = time.process_time()
            with torch.no_grad():
                matrix, events = self.policy.transition_for_context(context)
                self.transitions[key] = matrix.numpy().copy(), events.numpy().copy()
            self.preparation_cpu += time.process_time() - cpu
            self.preparation_calls += 1
        matrix, events = self.transitions[key]
        row = matrix[index]
        if np.min(row) < -2e-10 or abs(row.sum() - 1) > 2e-9:
            raise FloatingPointError("invalid finite transition row")
        # Roundoff clipping cannot silently mask the preceding mass checks.
        row = np.maximum(row, 0.)
        row /= row.sum()
        uniform = float(rng.random())
        after = min(int(np.searchsorted(np.cumsum(row), uniform, side="right")), len(row) - 1)
        return after, dict(event=index < 15 <= after, recovery=after < 15 <= index,
                           sampled=True, uniform=uniform, event_probability=float(events[index]))

    def storage_bytes(self):
        return sum(a.nbytes for a in self.network) + sum(a.nbytes for a in self.features.values()) + sum(
            a.nbytes + b.nbytes for a, b in self.transitions.values())


def run_episode(runtime, record, adapter, confusion, controller, seed, supervised=False):
    """Read payloads only on completion; labels only after a terminated task."""
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    folder = Path(record["folder"])
    public = json.loads((folder / "public.json").read_text())
    owner, oracle = Owner(public, folder, adapter), Oracle(public, confusion)
    index = 7 if runtime is not None and runtime.policy.cell is not None else 0
    rng = np.random.default_rng(seed)
    rows, decisions, prefix = [], [], []
    diagnostic_cpu = 0.
    while not owner.state["terminal"]:
        state = copy.deepcopy(owner.state)
        mask = legal(public, state)
        if runtime is None:
            q = oracle.q(state)
            scores = dict(q=[float(x) if m else 0. for x, m in zip(q, mask)],
                          belief=posterior(public, state, confusion))
        else:
            scores = runtime.predict(public, state, index)
        action = (fixed_action(state, mask, scores["belief"]) if controller == "fixed" else
                  int(np.argmax(np.where(mask, scores["q"], -np.inf))))
        old_index = index
        receipt = owner.step(action)
        event = dict(event=False, recovery=False, sampled=False)
        if action not in (0, 4, 5):
            context = transition_context(public, state, owner.state)
            if runtime is not None:
                index, event = runtime.advance(context, index, rng)
        cpu = time.process_time()
        teacher = oracle.q(state)
        belief_target = posterior(public, state, confusion)
        safe_teacher = [float(q) if m else 0. for q, m in zip(teacher, mask)]
        if supervised:
            rows.append(dict(world=record["id"], public=public, state=state,
                             prefix=copy.deepcopy(prefix), legal=mask, q=safe_teacher,
                             posterior=belief_target, latent_index=old_index, action=action,
                             occupancy="realized_greedy_snapshot; conditional-prefix reweighting prohibited"))
        chosen_q = float(scores["q"][action])
        selected_error = chosen_q - float(teacher[action])
        values = np.sort(np.asarray(scores["q"])[mask])
        best = float(np.max(teacher))
        metrics = dict(selected_q_error=selected_error, selected_q_squared_error=selected_error ** 2,
                       selected_margin=float(values[-1] - values[-2]),
                       oracle_regret=best - float(teacher[action]),
                       belief_squared_error=(scores["belief"] - belief_target) ** 2,
                       wrong_stop=action == 0 and best > .02,
                       wrong_submit=bool(action in (4, 5) and best - teacher[action] > .02),
                       terminal_sign_error=bool(action in (4, 5) and teacher[action] < -1e-12),
                       terminal_structure_error=max(abs(scores["q"][0]),
                           abs(scores["q"][4] - (1 - 2 * scores["belief"])),
                           abs(scores["q"][5] - (2 * scores["belief"] - 1))))
        diagnostic_cpu += time.process_time() - cpu
        decisions.append(dict(state=state, after=receipt["after"], action=action,
                              latent_index=old_index, latent_after=index, event=event,
                              scores=scores, teacher_q=safe_teacher, teacher_belief=belief_target,
                              completion=receipt["completion"], content=receipt["content"],
                              occupancy_key=list(occupancy_key(state)), **metrics))
        if action not in (0, 4, 5):
            prefix.append(context)
    label = json.loads((folder / "evaluator.json").read_text())["label"]
    outcome = evaluate_terminal(owner.state, label)
    execution_cpu = time.process_time() - start_cpu - diagnostic_cpu
    # Includes metadata/setup, content, transitions, decisions and terminal scoring.
    # Fitted-oracle diagnostics and later aggregate statistics are reported separately.
    aggregate = dict(**outcome, execution_cpu_seconds=execution_cpu,
                     diagnostic_cpu_seconds=diagnostic_cpu,
                     episode_wall_seconds=time.perf_counter() - start_wall,
                     decisions=len(decisions), events=sum(d["event"]["event"] for d in decisions),
                     recoveries=sum(d["event"]["recovery"] for d in decisions),
                     completed_content_calls=sum(d["content"] is not None and "failure" not in d["content"] for d in decisions),
                     failed_content_calls=sum(d["content"] is not None and "failure" in d["content"] for d in decisions),
                     content_cpu_seconds=sum(d["content"].get("total_cpu_seconds", 0.) for d in decisions if d["content"]),
                     payload_bytes=sum(d["content"].get("payload_bytes", 0) for d in decisions if d["content"]))
    for key in ("selected_q_squared_error", "oracle_regret", "belief_squared_error", "selected_margin"):
        aggregate[key] = float(np.mean([d[key] for d in decisions]))
    for key in ("wrong_stop", "wrong_submit", "terminal_sign_error"):
        aggregate[key] = sum(int(d[key]) for d in decisions)
    aggregate["terminal_structure_error"] = max(d["terminal_structure_error"] for d in decisions)
    return dict(world=record["id"], seed=seed, controller=controller, metrics=aggregate,
                decisions=decisions, final_state=owner.state, label_access_after_terminal=True), rows


def extend_behavior(data):
    """Recover completion impulses from original actual-read receipts exactly once."""
    for split in ("train", "validation"):
        rows = data[split]["rows"]
        for episode in data[split]["episodes"]:
            prefix = []
            for i, receipt in zip(episode["indices"], episode["receipts"]):
                row = rows[i]
                row["prefix"] = copy.deepcopy(prefix)
                if receipt["action"] not in (0, 4, 5):
                    prefix.append(transition_context(row["public"], receipt["before"], receipt["after"]))
    return data


def collect_visits(policy, records, adapter, confusion, seed):
    runtime = Runtime(policy)
    start = time.process_time()
    rows, episodes = [], []
    for i, record in enumerate(records):
        episode, states = run_episode(runtime, record, adapter, confusion, "value", seed + i, supervised=True)
        rows.extend(states)
        episodes.append(episode)
    return rows, dict(cpu_seconds=time.process_time() - start, records=len(rows),
                      world_count=len(records), episodes=episodes,
                      occupancy_sha256=hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())
