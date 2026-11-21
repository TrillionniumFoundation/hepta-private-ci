"""A train-only finite-MDP continuation baseline, not a network optimum proof.

The two actions are continue and reset.  A lower stopping boundary is a
projection of the discrete policy; its value gap is reported, never hidden.
No evaluation target is an argument to fitting or querying a boundary.
"""

from dataclasses import dataclass
import hashlib
import json

import numpy as np


@dataclass
class ContinuationBoundary:
    grid: np.ndarray
    transition: np.ndarray
    reset_transition: np.ndarray
    reward: np.ndarray
    reset_reward: np.ndarray
    value: np.ndarray
    q_continue: np.ndarray
    q_reset: np.ndarray
    thresholds: np.ndarray
    projected_value: np.ndarray
    occupancy: np.ndarray
    support: np.ndarray
    discount: float
    context_column: int | None
    training_digest: str
    reward_definition: str

    def query(self, observations, remaining):
        """Query observed context and a known remaining horizon, without labels."""
        observations = np.asarray(observations)
        if observations.ndim != 2 or not np.isfinite(observations).all():
            raise ValueError("observations must be a finite [batch,input] array")
        contexts = (np.zeros(len(observations), dtype=np.int64)
                    if self.context_column is None else
                    (observations[:, self.context_column] >= 0).astype(np.int64))
        remaining = np.broadcast_to(np.asarray(remaining, dtype=np.int64), contexts.shape)
        if np.any(remaining < 1) or np.any(remaining >= len(self.thresholds)):
            raise ValueError("remaining horizon is outside the frozen critic")
        return self.thresholds[remaining, contexts].copy()

    def report(self):
        advantage = self.q_continue[-1] - self.q_reset[-1]
        signs = (advantage.reshape(-1, len(self.grid)) >= 0).astype(np.int8)
        crossings = np.abs(np.diff(signs, axis=1)).sum(axis=1)
        gap = self.value[-1] - self.projected_value[-1]
        weights = self.occupancy / self.occupancy.sum()
        return {
            "claim": "finite observed MDP; scalar threshold projection, not global network optimality",
            "training_digest": self.training_digest,
            "reward_definition": self.reward_definition,
            "horizon": len(self.value) - 1,
            "discount": self.discount,
            "supported_states": int(self.support.sum()),
            "total_states": int(len(self.support)),
            "final_advantage_sign_changes_per_context": crossings.tolist(),
            "non_single_threshold_contexts": int((crossings > 1).sum()),
            "weighted_projection_value_gap": float(weights @ gap),
            "maximum_projection_value_gap": float(gap.max()),
            "thresholds": self.thresholds.tolist(),
        }

    def to_record(self):
        payload = {name: (value.tolist() if isinstance(value, np.ndarray) else value)
                   for name, value in vars(self).items()}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return {"schema": "hepta.continuation-mdp.v1", "payload": payload, "sha256": digest}

    @classmethod
    def from_record(cls, record):
        if set(record) != {"schema", "payload", "sha256"} or record["schema"] != "hepta.continuation-mdp.v1":
            raise ValueError("invalid continuation record schema")
        payload = record["payload"]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError("continuation record identity changed")
        scalar = {"discount", "context_column", "training_digest", "reward_definition"}
        restored = cls(**{key: value if key in scalar else np.asarray(value)
                          for key, value in payload.items()})
        rebuilt = solve_continuation(restored.transition, restored.reset_transition,
                                     restored.reward, restored.reset_reward, grid=restored.grid,
                                     occupancy=restored.occupancy, support=restored.support,
                                     horizon=len(restored.value) - 1, discount=restored.discount,
                                     context_column=restored.context_column,
                                     training_digest=restored.training_digest,
                                     reward_definition=restored.reward_definition)
        for field in ("value", "q_continue", "q_reset", "thresholds", "projected_value"):
            if not np.array_equal(getattr(restored, field), getattr(rebuilt, field)):
                raise ValueError("continuation solution differs from its declared finite model")
        return rebuilt


def solve_continuation(transition, reset_transition, reward, reset_reward, *,
                       grid, occupancy, support, horizon=12, discount=0.98,
                       context_column=None, training_digest="", reward_definition=""):
    """Solve a finite-horizon discrete Bellman/QVI and evaluate its projection."""
    grid = np.asarray(grid, dtype=np.float64)
    transition = np.asarray(transition, dtype=np.float64)
    reset_transition = np.asarray(reset_transition, dtype=np.float64)
    reward, reset_reward = np.asarray(reward), np.asarray(reset_reward)
    states = len(reward)
    if (grid.ndim != 1 or len(grid) < 2 or not np.isfinite(grid).all() or not np.all(np.diff(grid) > 0)
            or states % len(grid) or not 1 <= horizon <= 256
            or not 0 < discount <= 1 or reset_reward.shape != (states,)):
        raise ValueError("invalid finite MDP dimensions, grid, horizon or discount")
    for matrix in (transition, reset_transition):
        if (matrix.shape != (states, states) or not np.isfinite(matrix).all()
                or np.any(matrix < 0) or not np.allclose(matrix.sum(1), 1, rtol=0, atol=1e-10)):
            raise ValueError("each transition row must be a probability distribution")
    if not np.isfinite(reward).all() or not np.isfinite(reset_reward).all():
        raise ValueError("nonfinite reward")
    occupancy = np.asarray(occupancy, dtype=np.float64)
    support = np.asarray(support, dtype=bool)
    if (occupancy.shape != (states,) or not np.isfinite(occupancy).all() or np.any(occupancy < 0)
            or occupancy.sum() <= 0 or support.shape != (states,)):
        raise ValueError("invalid occupancy or support")
    groups, width = states // len(grid), len(grid)
    values = np.zeros((horizon + 1, states))
    qc, qr, projected = np.zeros_like(values), np.zeros_like(values), np.zeros_like(values)
    thresholds = np.zeros((horizon + 1, groups))
    edges = np.r_[grid[0] - (grid[1] - grid[0]) / 2,
                  (grid[1:] + grid[:-1]) / 2,
                  grid[-1] + (grid[-1] - grid[-2]) / 2]
    for h in range(1, horizon + 1):
        qc[h] = reward + discount * (transition @ values[h - 1])
        qr[h] = reset_reward + discount * (reset_transition @ values[h - 1])
        values[h] = np.maximum(qc[h], qr[h])
        policy = np.zeros(states, dtype=bool)
        for group in range(groups):
            sl = slice(group * width, (group + 1) * width)
            weights = occupancy[sl] + 1e-12
            scores = [weights @ np.where(np.arange(width) < cut, qr[h, sl], qc[h, sl])
                      for cut in range(width + 1)]
            cut = int(np.argmax(scores))
            thresholds[h, group] = edges[cut]
            policy[sl] = np.arange(width) < cut
        # Evaluate this projected policy on its own continuation, not on V*.
        projected[h] = np.where(
            policy, reset_reward + discount * (reset_transition @ projected[h - 1]),
            reward + discount * (transition @ projected[h - 1]))
    return ContinuationBoundary(grid, transition, reset_transition, reward, reset_reward,
                                values, qc, qr, thresholds, projected, occupancy,
                                support, discount, context_column, training_digest,
                                reward_definition)


def fit_continuation(observations, *, split, grid=None, context_column=1,
                     running_rewards=None, horizon=12, discount=0.98,
                     reset_value=0.5, reset_cost=0.25, operating_target=0.5,
                     reward_definition=None):
    """Fit empirical continue transitions using only a declared training split.

    State is (sign of observed context, quantized first observation). Reset
    retains context and moves to reset_value. Unseen continue states self-loop
    and remain explicitly unsupported. This reset law is a modeling assumption.
    Explicit rewards, when supplied, must be training observations. Otherwise
    the declared utility is -(state-operating_target)^2, not supervised MSE.
    """
    if split != "train":
        raise ValueError("a continuation critic may only fit the train split")
    x = np.asarray(observations, dtype=np.float64)
    if x.ndim != 3 or x.shape[1] < 2 or not np.isfinite(x).all():
        raise ValueError("training observations must be finite [samples,time,input]")
    if context_column is not None and not 0 <= context_column < x.shape[-1]:
        raise ValueError("context column is unavailable")
    grid = np.asarray(np.linspace(-1.5, 1.5, 9) if grid is None else grid, dtype=np.float64)
    groups, width = (1 if context_column is None else 2), len(grid)
    indices = np.abs(x[:, :, 0, None] - grid).argmin(-1)
    contexts = np.zeros(indices.shape, dtype=np.int64) if context_column is None else (
        x[:, :, context_column] >= 0).astype(np.int64)
    state = contexts * width + indices
    counts = np.zeros((groups * width, groups * width))
    np.add.at(counts, (state[:, :-1].ravel(), state[:, 1:].ravel()), 1)
    occupancy = counts.sum(1)
    support = occupancy >= 2
    transition = counts.copy()
    empty = occupancy == 0
    transition[empty, np.flatnonzero(empty)] = 1
    transition /= transition.sum(1, keepdims=True)
    reset = np.zeros_like(transition)
    reset_bin = int(np.abs(grid - reset_value).argmin())
    for group in range(groups):
        reset[group * width:(group + 1) * width, group * width + reset_bin] = 1
    reward = -np.tile((grid - operating_target) ** 2, groups)
    digest = hashlib.sha256(x.tobytes() + str(x.shape).encode())
    definition = f"-(state-{operating_target})^2; reset utility=-{reset_cost}"
    if running_rewards is not None:
        r = np.asarray(running_rewards, dtype=np.float64)
        if r.shape != x.shape[:2] or not np.isfinite(r).all() or not reward_definition:
            raise ValueError("explicit training rewards need matching shape and definition")
        sums = np.zeros_like(reward)
        np.add.at(sums, state[:, :-1].ravel(), r[:, :-1].ravel())
        reward[support] = sums[support] / occupancy[support]
        digest.update(r.tobytes())
        definition = reward_definition + "; unsupported states retain declared quadratic prior"
    return solve_continuation(transition, reset, reward, np.full_like(reward, -reset_cost),
                              grid=grid, occupancy=occupancy, support=support,
                              horizon=horizon, discount=discount, context_column=context_column,
                              training_digest=digest.hexdigest(), reward_definition=definition)
