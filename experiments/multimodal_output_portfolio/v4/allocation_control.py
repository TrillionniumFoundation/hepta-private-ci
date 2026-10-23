"""Frozen H2 finite modality-allocation model and initial-feedback plan oracle."""

from itertools import product
import json
from pathlib import Path
import time

import numpy as np
import torch

from allocation_model import INIT_COST, REFINE_COST, EMIT_COST
from metrics import score_outputs
from model import MODALITIES
from risk import entropic_ce


PLANS = tuple(plan for length in range(3) for plan in product(range(4), repeat=length))


def read_protocol():
    return json.loads(Path(__file__).with_name("protocol.json").read_text())


def direction(seed):
    value = np.random.default_rng(seed).normal(size=64)
    return (value * (.8 / np.sqrt(np.mean(value ** 2)))).astype(np.float32)


def noise_support(seed):
    if type(seed) is not int or not 0 <= seed < 2**20:
        raise ValueError("bounded integer study seed required")
    initial = np.stack([direction(4300000 + 1000 * seed + 10 * m) for m in range(4)])
    banks = np.empty((2, 4, 3, 64), dtype=np.float32)
    for depth, modality in product(range(2), range(4)):
        value = direction(4600000 + 1000 * seed + 100 * (depth + 1) + modality)
        banks[depth, modality] = np.stack((-value, np.zeros(64), value))
    coefficients = np.array([1., .75, .5, .25], dtype=np.float32)
    modes = np.stack([coefficients[(np.arange(4) - mode) % 4, None] * initial for mode in range(4)])
    return initial, banks, modes


def choose(scores, eligible):
    if scores.ndim != 2 or scores.shape != eligible.shape or not np.isfinite(scores).all():
        raise ValueError("finite candidate table and matching eligibility required")
    if not np.all(eligible.any(1)):
        raise ValueError("no feasible action")
    selected = eligible.argmax(1).astype(np.int64)
    rows = np.arange(len(scores))
    for action in range(scores.shape[1]):
        take = eligible[:, action] & (scores[:, action] > scores[rows, selected] + 1e-12)
        selected[take] = action
    return selected


class AllocationPolicy:
    """Arrays are immutable; all values include future costs and exclude INIT."""

    def __init__(self, model, targets, seed):
        self.seed = seed
        protocol = read_protocol()
        self.gamma = protocol["objective"]["gamma"]
        self.price = .015 / REFINE_COST
        self.probabilities = np.array(protocol["disturbance_design"]["branch_probabilities"])
        self.tree, self.policy = {}, {}
        started, cpu = time.perf_counter(), time.process_time()
        before = model.work_receipt()["linear_macs"]
        with torch.inference_mode():
            self._build_tree(model, targets)
        self._solve()
        for array in (*self.tree.values(), *self.policy.values()):
            array.flags.writeable = False
        self.receipt = {"seed": seed, "checkpoint_sha256": model.checkpoint_sha256,
                        "weight_sha256": model.weight_sha256, "nodes": 5024,
                        "tree_and_clean_forward_linear_macs": model.work_receipt()["linear_macs"] - before,
                        "wall_seconds": time.perf_counter() - started,
                        "process_cpu_seconds": time.process_time() - cpu,
                        "root_J": {arm: self.root_utility(arm) for arm in (
                            "dynamic", "myopic", "initial_feedback_committed_open_loop", "clean_no_disturbance_reference")}}

    def _build_tree(self, model, targets):
        initial, banks, modes = noise_support(self.seed)
        self.tree.update(initial_directions=initial, future_banks=banks, initial_modes=modes)
        q = torch.eye(8)
        anchors = model.anchor_tensor(q)
        clean = anchors[:, None].expand(-1, 4, -1).clone()
        self._save_node("clean", clean, model.decode_tensor(clean), np.arange(8), targets)
        current = anchors.repeat_interleave(4, 0)[:, None] + torch.from_numpy(np.tile(modes, (8, 1, 1)))
        qs, repeated_anchors = q.repeat_interleave(4, 0), anchors.repeat_interleave(4, 0)
        for depth in range(3):
            classes = np.repeat(np.arange(8), 4 * 12 ** depth)
            self._save_node(str(depth), current, model.decode_tensor(current), classes, targets)
            if depth == 2:
                break
            count = len(current)
            next_q, next_anchor = qs.repeat_interleave(12, 0), repeated_anchors.repeat_interleave(12, 0)
            children = current.repeat_interleave(12, 0)
            for modality in range(4):
                index = (torch.arange(count)[:, None] * 12 + modality * 3 + torch.arange(3)).reshape(-1)
                noise = np.tile(banks[depth, modality], (count, 1))
                children[index] = model.refine_tensor(next_q[index], children[index], modality,
                                                       noise, next_anchor[index])
            current, qs, repeated_anchors = children, next_q, next_anchor

    def _save_node(self, suffix, latents, outputs, classes, targets):
        arrays = {name: value.numpy().copy() for name, value in outputs.items()}
        if suffix == "clean":
            self.tree["clean_latents"] = latents.numpy().copy()
            self.tree.update({"clean_outputs_" + name: value for name, value in arrays.items()})
            self.tree["clean_loss"] = score_outputs(arrays, classes, targets)["loss"]
        else:
            self.tree["latents_" + suffix] = latents.numpy().copy()
            self.tree.update({"outputs_" + suffix + "_" + name: value for name, value in arrays.items()})
            self.tree["loss_" + suffix] = score_outputs(arrays, classes, targets)["loss"]

    def _stop(self, depth):
        return -self.tree["loss_" + str(depth)] - self.price * EMIT_COST

    def _solve(self):
        for arm in ("dynamic", "myopic"):
            for depth in (2, 1, 0):
                stop = self._stop(depth)
                scores, eligible = np.zeros((len(stop), 5)), np.zeros((len(stop), 5), dtype=bool)
                scores[:, 0], eligible[:, 0] = stop, True
                if depth < 2:
                    realized = self.policy[arm + "_values_" + str(depth + 1)].reshape(-1, 4, 3)
                    next_values = realized if arm == "dynamic" else self._stop(depth + 1).reshape(-1, 4, 3)
                    scores[:, 1:] = entropic_ce(next_values, self.probabilities, self.gamma) - .015
                    eligible[:, 1:] = True
                selected = choose(scores, eligible)
                values = scores[np.arange(len(stop)), selected].copy()
                if arm == "myopic" and depth < 2:
                    continuation = entropic_ce(realized, self.probabilities, self.gamma) - .015
                    take = selected > 0
                    values[take] = continuation[np.flatnonzero(take), selected[take] - 1]
                self.policy.update({arm + "_scores_" + str(depth): scores,
                                    arm + "_actions_" + str(depth): selected,
                                    arm + "_values_" + str(depth): values})
        roots = np.arange(32)
        table = np.column_stack([self.sequence_value(0, roots, plan) for plan in PLANS])
        selected = choose(table, np.ones_like(table, dtype=bool))
        self.policy.update(plan_values=table, plan_choice=selected,
                           plan_selected_value=table[roots, selected].copy(),
                           plan_lengths=np.array([len(plan) for plan in PLANS], dtype=np.int64),
                           plans=np.array([(*plan, *([-1] * (2 - len(plan)))) for plan in PLANS], dtype=np.int64))

    def sequence_value(self, depth, nodes, sequence):
        nodes = np.asarray(nodes, dtype=np.int64)
        if depth + len(sequence) > 2 or any(type(m) is not int or not 0 <= m < 4 for m in sequence):
            raise ValueError("registered finite plan required")
        if not sequence:
            return self._stop(depth)[nodes]
        children = nodes[:, None] * 12 + sequence[0] * 3 + np.arange(3)
        future = self.sequence_value(depth + 1, children.reshape(-1), sequence[1:]).reshape(-1, 3)
        return entropic_ce(future, self.probabilities, self.gamma) - .015

    def match(self, feedback, parent=None, previous_modality=None, clean=False):
        depth, condition = feedback["depth"], feedback["condition"]
        actual = feedback["latents"].detach().cpu().numpy()
        if (type(condition) is not int or not 0 <= condition < 8
                or type(depth) is not int or not 0 <= depth <= 2
                or actual.shape != (1, 4, 64) or not np.isfinite(actual).all()):
            raise ValueError("registered actual current latent feedback required")
        if clean:
            candidates, states = np.array([condition]), self.tree["clean_latents"]
        elif depth == 0:
            candidates, states = np.arange(4 * condition, 4 * condition + 4), self.tree["latents_0"]
        else:
            if parent is None or previous_modality not in range(4):
                raise ValueError("causal prior action and node required")
            candidates = parent * 12 + previous_modality * 3 + np.arange(3)
            states = self.tree["latents_" + str(depth)]
        errors = np.max(np.abs(states[candidates] - actual[0]), axis=(1, 2))
        matches = candidates[errors <= 2e-5]
        if not len(matches):
            raise ValueError("current latent is outside frozen finite support")
        if len(matches) > 1 and not clean:
            for arm in ("dynamic", "myopic"):
                scores = self.policy[arm + "_scores_" + str(depth)][matches]
                if np.max(np.abs(scores - scores[0])) > 1e-10:
                    raise ValueError("ambiguous latent matches have different action values")
            for remaining in PLANS:
                if len(remaining) <= 2 - depth:
                    values = self.sequence_value(depth, matches, remaining)
                    if np.max(np.abs(values - values[0])) > 1e-10:
                        raise ValueError("ambiguous latent matches have different committed-plan values")
        return int(candidates[errors.argmin()]), float(errors.min())

    def decision(self, arm, depth, node, plan=None):
        scores, eligible = np.zeros(5), np.zeros(5, dtype=bool)
        if arm in ("dynamic", "myopic"):
            scores = self.policy[arm + "_scores_" + str(depth)][node].copy()
            eligible[:] = depth < 2
            eligible[0] = True
        elif arm == "initial_feedback_committed_open_loop":
            if plan not in PLANS or depth > len(plan):
                raise ValueError("the INIT-bound committed plan is required")
            action = plan[depth] + 1 if depth < len(plan) else 0
            scores[action] = self.sequence_value(depth, np.array([node]), plan[depth:])[0]
            eligible[action] = True
        elif arm == "clean_no_disturbance_reference":
            if depth != 0:
                raise ValueError("clean reference emits immediately")
            scores[0] = -self.tree["clean_loss"][node] - self.price * EMIT_COST
            eligible[0] = True
        else:
            raise ValueError("unknown registered arm")
        action = int(choose(scores[None], eligible[None])[0])
        return {"action": action, "scores": scores, "eligible": eligible}

    def root_utility(self, arm):
        if arm in ("dynamic", "myopic"):
            values = self.policy[arm + "_values_0"]
        elif arm == "initial_feedback_committed_open_loop":
            values = self.policy["plan_selected_value"]
        elif arm == "clean_no_disturbance_reference":
            values = -self.tree["clean_loss"] - self.price * EMIT_COST
        else:
            raise ValueError("unknown arm")
        return float(values.mean() - self.price * INIT_COST)

    def save_tables(self, tree_path, policy_path):
        if Path(tree_path).exists() or Path(policy_path).exists():
            raise FileExistsError("existing evidence must not be overwritten")
        np.savez_compressed(tree_path, **self.tree)
        np.savez_compressed(policy_path, **self.policy)
