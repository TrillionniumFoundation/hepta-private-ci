"""TRAIN-only incumbent advantages. This module receives no evaluator law."""
import time

import numpy as np

from artifact_io import canonical, sha
from vendor import planning as p


TERMINAL = (0, 4, 5)


def backward_values(order, actions, terminal_rewards, edges):
    values = np.zeros(len(actions), dtype=np.float64)
    for index in reversed(order):
        action = int(actions[index])
        if action in TERMINAL:
            values[index] = terminal_rewards[index, action]
        else:
            total = 0.
            for probability, after, fee in edges[index][action - 1]:
                if probability:
                    total += probability * (float(values[after]) - fee)
            values[index] = total
    return values


def forward_occupancy(order, initial_index, actions, edges):
    occupancy = np.zeros(len(actions), dtype=np.float64)
    occupancy[initial_index] = 1.
    for index in order:
        action = int(actions[index])
        if action in TERMINAL:
            continue
        for probability, after, _fee in edges[index][action - 1]:
            if probability:
                occupancy[after] += float(occupancy[index]) * probability
    terminal_mass = sum(float(occupancy[i]) for i, a in enumerate(actions) if a in TERMINAL)
    if abs(terminal_mass - 1.) > 2e-11:
        raise ArithmeticError("incumbent occupancy does not conserve probability")
    return occupancy, terminal_mass


def anchored_targets(q_continuation, predicted_scores, terminal_rewards):
    terminal_actions = np.array([TERMINAL[int(np.argmax(row[list(TERMINAL)]))]
                                 for row in predicted_scores], dtype=np.int64)
    indices = np.arange(len(terminal_actions))
    predicted_terminal = predicted_scores[indices, terminal_actions]
    own_terminal = terminal_rewards[indices, terminal_actions]
    targets = predicted_terminal[:, None] + q_continuation - own_terminal[:, None]
    return targets, terminal_actions, predicted_terminal, own_terminal


def state_weights(mask, occupancy, world_count, mixture):
    continuation = np.asarray(mask[:, 1:4], dtype=float)
    counts = continuation.sum(axis=1)
    eligible = counts > 0
    eligible_count = int(eligible.sum())
    total_occupancy = float(occupancy[eligible].sum())
    if eligible_count == 0 or total_occupancy <= 0:
        raise ValueError("missing legal continuation support or incumbent initial occupancy")
    uniform = np.zeros(len(counts))
    uniform[eligible] = 1. / eligible_count
    occupied = np.zeros(len(counts))
    occupied[eligible] = occupancy[eligible] / total_occupancy
    mixed = mixture * occupied + (1. - mixture) * uniform
    denominators = np.where(eligible, counts * world_count, 1.)
    wm = continuation * (mixed / denominators)[:, None]
    wu = continuation * (uniform / denominators)[:, None]
    if not np.isclose(wm.sum(), 1. / world_count, rtol=0, atol=2e-14):
        raise ArithmeticError("world mixture weights not normalized")
    if not np.isclose(wu.sum(), 1. / world_count, rtol=0, atol=2e-14):
        raise ArithmeticError("world uniform weights not normalized")
    return wm, wu, dict(eligible_states=eligible_count,
                       eligible_occupancy_mass=total_occupancy,
                       occupied_eligible_states=int(np.count_nonzero(occupancy[eligible])),
                       mixed_weight_sum=float(wm.sum()), uniform_weight_sum=float(wu.sum()))


class TrainWorld:
    """Complete lawful support, with charges preserved in every state identity."""
    def __init__(self, ctx, public, policy, incumbent, world_count, protocol):
        start, wall = time.process_time(), time.perf_counter()
        self.ctx, self.public, self.incumbent = ctx, public, incumbent
        enum_start = time.process_time()
        state_map = p.enumerate_states(ctx, public, True, protocol["state_caps"]["full_per_world"])
        enumeration_cpu = time.process_time() - enum_start
        self.keys, self.states = list(state_map), list(state_map.values())
        self.indices = {key: i for i, key in enumerate(self.keys)}
        self.initial_index = self.indices[canonical(ctx.initial(public))]
        self.order = sorted(range(len(self.states)), key=lambda i: self.states[i]["tick"])
        self.world = p.WorldPolicy(ctx, public, policy, None)
        self.own = ctx.Oracle(public, p.OwnTableLaw(policy, ctx), policy.confusion)
        hidden, scores, masks, terminal_rewards, analytic = [], [], [], [], []
        posterior_gap = 0.
        for state in self.states:
            feature, bank = self.world.feature(state)
            qs, _belief = ctx.predicted(incumbent, feature)
            posterior = self.own.posterior(state)
            posterior_gap = max(posterior_gap, abs(posterior - bank))
            hidden.append(feature)
            scores.append(qs)
            masks.append(ctx.legal(public, state))
            terminal_rewards.append([0., 0., 0., 0., 1 - 2 * posterior, 2 * posterior - 1])
            analytic.append(bank)
        if posterior_gap > 2e-12:
            raise ArithmeticError("checkpoint bank7 differs from own-law terminal posterior")
        self.H, self.base_scores = np.asarray(hidden), np.asarray(scores)
        self.masks, self.terminal_rewards = np.asarray(masks), np.asarray(terminal_rewards)
        self.analytic = np.asarray(analytic)
        self.base_actions = np.where(self.masks, self.base_scores, -np.inf).argmax(axis=1)
        self.edges, probability_error = [], 0.
        for state in self.states:
            row = []
            for action in (1, 2, 3):
                outgoing = []
                if ctx.legal(public, state)[action]:
                    total = 0.
                    for probability, completion in ctx.outcomes(public, state, action, self.own):
                        after = ctx.successor(public, state, action, completion)
                        if after["tick"] != state["tick"] + 1:
                            raise ArithmeticError("task graph is not the declared tick DAG")
                        following = self.indices[canonical(after)]
                        fee = after["charges"] - state["charges"]
                        if not np.isfinite(probability) or probability < 0 or fee < 0:
                            raise ArithmeticError("invalid own-law edge")
                        outgoing.append((float(probability), following, float(fee)))
                        total += probability
                    probability_error = max(probability_error, abs(total - 1.))
                row.append(outgoing)
            self.edges.append(row)
        if probability_error > 2e-11:
            raise ArithmeticError("own-law outgoing probabilities not normalized")
        self.values = backward_values(self.order, self.base_actions, self.terminal_rewards, self.edges)
        q_continuation = np.zeros((len(self.states), 3))
        for index, row in enumerate(self.edges):
            for a, outgoing in enumerate(row):
                total = 0.
                for probability, after, fee in outgoing:
                    if probability:
                        total += probability * (float(self.values[after]) - fee)
                q_continuation[index, a] = total
        self.raw_targets = q_continuation
        self.targets, self.terminal_actions, predicted_terminal, own_terminal = anchored_targets(
            q_continuation, self.base_scores, self.terminal_rewards)
        occupancy, terminal_mass = forward_occupancy(self.order, self.initial_index,
                                                    self.base_actions, self.edges)
        self.W, self.WU, weights = state_weights(self.masks, occupancy, world_count,
                                                protocol["optimization"]["occupancy_mixture"])
        # Independent old recursive executor, with its own transition traversal.
        reference, reference_nodes = ctx.policy_value(public, incumbent,
            lambda _public, state: self.world.feature(state)[0], self.own)
        if float(reference) != float(self.values[self.initial_index]):
            raise ArithmeticError("DAG incumbent utility differs from frozen recursive executor")
        selected_q = np.where(self.masks, self.base_scores, -np.inf)
        # TRAIN-only opportunity diagnostic; never an additional held-out arm.
        ideal_scores = selected_q.copy()
        ideal_scores[:, 1:4] = self.targets
        ideal_actions = np.where(self.masks, ideal_scores, -np.inf).argmax(axis=1)
        ideal_values = backward_values(self.order, ideal_actions, self.terminal_rewards, self.edges)
        self.report = dict(world_id=public["id"], full_states=len(self.states),
            enumeration_cpu_seconds=enumeration_cpu, feature_cpu_seconds=self.world.feature_cpu_seconds,
            posterior_identity_max=posterior_gap, probability_sum_error_max=probability_error,
            incumbent_terminal_mass=terminal_mass, incumbent_utility=float(reference),
            incumbent_reference_nodes=reference_nodes, reference_utility_exact_match=True,
            ideal_anchor_policy_own_utility=float(ideal_values[self.initial_index]),
            terminal_anchor_offset_min=float((predicted_terminal - own_terminal).min()),
            terminal_anchor_offset_max=float((predicted_terminal - own_terminal).max()),
            state_order_sha256=sha(canonical(self.keys).encode()),
            edges_sha256=sha(canonical(self.edges).encode()), H_sha256=sha(self.H.tobytes()),
            targets_sha256=sha(self.targets.tobytes()), raw_targets_sha256=sha(self.raw_targets.tobytes()),
            W_sha256=sha(self.W.tobytes()), uniform_W_sha256=sha(self.WU.tobytes()),
            occupancy_sha256=sha(occupancy.tobytes()), weights=weights,
            total_preparation_cpu_seconds=time.process_time() - start,
            total_preparation_wall_seconds=time.perf_counter() - wall)

    def score(self, theta, structural="head", compiled=None):
        """Actual F64 head decisions, exact expectation over its reachable own DAG."""
        start, wall = time.process_time(), time.perf_counter()
        values, actions = {}, {}
        def value(index):
            if index in values:
                return values[index]
            if structural == "J":
                row = compiled["rows"][p.markov_key(self.states[index])]
                if row["legal"] != self.masks[index].tolist():
                    raise ArithmeticError("structural TRAIN legal mask mismatch")
                scores = np.asarray(row["q"])
            else:
                scores, _belief = self.ctx.predicted(theta, self.H[index])
                if structural == "P":
                    scores[4:6] = [1 - 2 * self.analytic[index], 2 * self.analytic[index] - 1]
            action = int(np.where(self.masks[index], scores, -np.inf).argmax())
            actions[index] = action
            if action in TERMINAL:
                result = float(self.terminal_rewards[index, action])
            else:
                result = 0.
                for probability, after, fee in self.edges[index][action - 1]:
                    if probability:
                        result += probability * (value(after) - fee)
            values[index] = result
            return result
        result = value(self.initial_index)
        if not np.isfinite(result):
            raise ArithmeticError("nonfinite TRAIN task utility")
        return dict(utility=result, visited_unique_states=len(values),
                    selected_actions_sha256=sha(canonical(sorted(actions.items())).encode()),
                    cpu_seconds=time.process_time() - start, wall_seconds=time.perf_counter() - wall,
                    cache_scope="complete TRAIN features and own transition DAG shared among all candidate paths")
