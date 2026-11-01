"""Conditional raw-world execution from actual intermediate prefixes."""

import time

import numpy as np

from experiments.hcsn_regeneration_content_20261031 import policy, policy_audit
from experiments.hcsn_regeneration_content_20261031.content_tasks import multimodal_support


class PendingRead(Exception):
    def __init__(self, slot):
        self.slot = slot


class LazyWorld(policy_audit.World):
    """Unknown unread outcomes are integrated, never passed to the actor."""

    def read(self, slot):
        if self._outcomes[slot] < 0:
            raise PendingRead(slot)
        return super().read(slot)


class ForcedPrefix:
    def __init__(self, following, history, first_action):
        self.following, self.history, self.first_action = following, history, first_action

    def choose(self, model, state, config):
        selected, scores = self.following.choose(model, state, config)
        if state.slot < len(self.history):
            return ("SKIP" if self.history[state.slot] == -1 else "READ"), scores
        if state.slot == len(self.history):
            return self.first_action, scores
        return selected, scores


def conditional_execution(graph, controller, history, first_action, expected, sink=None, support=multimodal_support):
    """Enumerate independently by latent label and actually requested raw reads."""
    cpu, wall = time.process_time(), time.perf_counter()
    config, model = graph.config, graph.model
    likelihoods = [support(m, config.q_a, config.q_b)[1] for m in config.modalities]
    label_weights = np.array([1 - config.prior, config.prior], dtype=float)
    prefix_outcomes = [-1] * len(config.dts)
    for slot, observed in enumerate(history):
        if observed >= 0:
            label_weights *= likelihoods[slot][:, observed]
            prefix_outcomes[slot] = observed
    label_weights /= label_weights.sum()
    prefix_fee = sum(config.skip_cost if i < 0 else config.read_cost for i in history)
    forced = ForcedPrefix(controller, history, first_action)
    value, mass, fee_sum, correctness, maximum = 0., 0., 0., 0., 0.
    leaves, expansions, failures = 0, 0, 0
    for label, posterior in enumerate(label_weights):
        stack = [(prefix_outcomes.copy(), float(posterior))]
        while stack:
            outcomes, weight = stack.pop()
            world = LazyWorld(f"conditional:{label}:{outcomes}", label, outcomes, config, support)
            try:
                result = policy_audit.execute(model, config, support, forced, world, graph)
            except PendingRead as pending:
                expansions += 1
                for outcome, probability in enumerate(likelihoods[pending.slot][label]):
                    child = outcomes.copy(); child[pending.slot] = outcome
                    stack.append((child, weight * float(probability)))
                continue
            if tuple(result["final_history"][:len(history)]) != tuple(history):
                raise AssertionError("Forced prefix did not reproduce accepted history")
            step = result["steps"][len(history)]
            if step["state_before_sha256"] != policy.state_digest(graph.nodes[history]["state"]):
                raise AssertionError("Intermediate checkpoint state mismatch")
            if step["executed"] != first_action:
                raise AssertionError("Forced first action was not executed")
            failures += sum(row["guard_rejected"] for row in result["steps"])
            suffix_value, suffix_fee = result["return"] + prefix_fee, result["fee"] - prefix_fee
            value += weight * suffix_value
            fee_sum += weight * suffix_fee
            correctness += weight * result["correct"]
            mass += weight; leaves += 1
            maximum = max(maximum, result["max_graph_state_error"])
            if sink is not None:
                sink({"prefix": history, "forced_action": first_action, "conditional_weight": weight,
                      "label_evaluator_only": label, "assigned_outcomes_evaluator_only": outcomes,
                      "prefix_fee": prefix_fee, "suffix_return": suffix_value,
                      "execution": result})
    errors = {"mass": abs(mass - 1), "qpi": abs(value - expected),
              "complete_fee": abs(value - (correctness - fee_sum)), "state": maximum}
    if failures or max(errors.values()) >= 2e-10:
        raise AssertionError({"errors": errors, "guard_fallbacks": failures})
    return {"prefix": history, "forced_action": first_action, "expected_qpi": expected,
            "actual_suffix_return": value, "correctness": correctness, "complete_suffix_fee": fee_sum,
            "probability_mass": mass, "complete_worlds": leaves, "branch_expansion_executions": expansions,
            "guard_fallbacks": failures, "errors": errors,
            "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall}


def select_prefixes(graph, evaluated):
    selected = [()]
    for slot in range(1, len(graph.config.dts)):
        possible = [(sum(r["occupancy"].get(h, 0.) for r in evaluated), h)
                    for h in graph.nodes if len(h) == slot]
        occupied = [(mass, history) for mass, history in possible if mass > 0]
        if occupied:
            selected.append(sorted(occupied, key=lambda row: (-row[0], row[1]))[0][1])
    return selected


def paired_execution(graph, controllers, count, seed, sink):
    rows = {name: {"returns": [], "correctness": [], "fees": [], "actor_cpu": 0.,
                   "actor_wall": 0., "stages_cpu": {}, "guard_fallbacks": 0} for name in controllers}
    for original in policy_audit.sampled_worlds(graph.config, multimodal_support, count, seed):
        manifest = original.manifest()
        for name, controller in controllers.items():
            world = policy_audit.World(manifest["world_id"], manifest["hidden_label_evaluator_only"],
                                      manifest["outcomes_evaluator_only"], graph.config, multimodal_support)
            result = policy_audit.execute(graph.model, graph.config, multimodal_support, controller, world, graph)
            row = rows[name]
            row["returns"].append(result["return"]); row["correctness"].append(result["correct"])
            row["fees"].append(result["fee"])
            row["actor_cpu"] += result["total_cpu_seconds"]; row["actor_wall"] += result["total_wall_seconds"]
            row["guard_fallbacks"] += sum(step["guard_rejected"] for step in result["steps"])
            for stage, elapsed in result["phase_cpu_seconds"].items():
                row["stages_cpu"][stage] = row["stages_cpu"].get(stage, 0.) + elapsed
            sink({"controller": name, "source": manifest, "execution": result})
    if any(r["guard_fallbacks"] for r in rows.values()):
        raise AssertionError("Unexpected guard fallback")
    return rows
