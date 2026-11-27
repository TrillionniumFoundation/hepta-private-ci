"""PRED-1 finite hidden-state tool simulator; never a real-tool success claim.

The actor sees arriving observations and previous actions. Only the evaluator
receives the latent state and exact Bayes distributions. Future labels never
enter the public history. All simulator costs are dimensionless work units.
"""

from dataclasses import dataclass
from hashlib import sha256

import numpy as np

from .contracts import Evidence, JOINT_SUPPORT, allowed_mask


HORIZONS = (1, 3, 6)
ACTIONS = ("direct_zero", "direct_one", "verify_execute", "defer_retry")
INPUT_DIM = 16
ACTION_DIM = 7
SCHEMA = "pred1-finite-tools-v1"


@dataclass(frozen=True)
class SensorEvent:
    measured_at: int
    observed_at: int
    sensor: int  # 0 = slow task context; 1 = fast resource condition
    value: int


@dataclass(frozen=True)
class PublicHistory:
    actions: tuple[int, ...]
    events: tuple[SensorEvent, ...]


@dataclass(frozen=True)
class EvaluatorOnly:
    bayes_joint: np.ndarray  # N x horizons x actions x joint classes
    realized_class: np.ndarray  # Same latent episode and paired random draws
    sampled_training_class: np.ndarray


@dataclass(frozen=True)
class Dataset:
    x: np.ndarray
    query: np.ndarray
    allowed: np.ndarray
    groups: tuple[str, ...]
    legal_actions: np.ndarray
    deadline: np.ndarray
    remaining_budget: np.ndarray
    prefix_cost: np.ndarray
    observation_counts: dict[str, int]
    evaluator: EvaluatorOnly

    def fingerprint(self):
        digest = sha256("\n".join(self.groups).encode())
        for value in (
            self.x,
            self.query,
            self.allowed,
            self.legal_actions,
            self.deadline,
            self.remaining_budget,
            self.prefix_cost,
            self.evaluator.bayes_joint,
            self.evaluator.realized_class,
            self.evaluator.sampled_training_class,
        ):
            digest.update(str((value.shape, value.dtype.str)).encode())
            digest.update(np.ascontiguousarray(value).tobytes())
        return digest.hexdigest()


def transition(action):
    """Known simulator dynamics for the evaluator, with a persistent slow bit."""
    if action not in (0, 1, 2):
        raise ValueError("invalid history action")
    matrix = np.zeros((4, 4))
    for slow in (0, 1):
        for fast in (0, 1):
            p_one = (
                (0.08 if fast == 0 else 0.92)
                if action == 0
                else ((0.75 if fast == 0 else 0.25) if action == 1 else 0.15)
            )
            matrix[2 * slow + fast, 2 * slow : 2 * slow + 2] = (1 - p_one, p_one)
    return matrix


def encode_history(history, decision_at):
    """Causal arrival-order encoder, including measurement lag and missingness."""
    if not 0 <= decision_at < len(history.actions) <= 256:
        raise ValueError("invalid public history extent")
    x = np.zeros((decision_at + 1, INPUT_DIM))
    for t, action in enumerate(history.actions[: decision_at + 1]):
        if action not in (0, 1, 2):
            raise ValueError("invalid public action")
        x[t, action] = 1
        x[t, 13] = 1  # elapsed simulation tick
        x[t, 14] = t / 16
    for event in history.events:
        if event.observed_at > decision_at:
            continue
        if not 0 <= event.measured_at <= event.observed_at or event.sensor not in (
            0,
            1,
        ):
            raise ValueError("invalid sensor event")
        if event.value not in (0, 1):
            raise ValueError("invalid sensor value")
        lag = event.observed_at - event.measured_at
        if lag > 3:
            raise ValueError("sensor delay exceeds registered support")
        index = 3 if event.sensor == 0 else 5 + 2 * lag
        if x[event.observed_at, index + 1] != 0:
            raise ValueError("duplicate sensor measurement slot")
        x[event.observed_at, index : index + 2] = (2 * event.value - 1, 1)
        x[event.observed_at, 15] += 0.1
    return x


def bayes_belief(history, decision_at):
    """Re-filter delayed observations at their measurement times, without lookahead."""
    likelihood = np.ones((decision_at + 1, 4))
    for event in history.events:
        if event.observed_at > decision_at:
            continue
        accuracy = 0.92 if event.sensor == 0 else 0.84
        for state in range(4):
            bit = state // 2 if event.sensor == 0 else state % 2
            likelihood[event.measured_at, state] *= (
                accuracy if bit == event.value else 1 - accuracy
            )
    belief = np.full(4, 0.25)
    for t in range(decision_at + 1):
        if t:
            belief = belief @ transition(history.actions[t])
        belief *= likelihood[t]
        belief /= belief.sum()
    return belief


def conditional_joint(state, action, horizon):
    """Explicit correlated p(outcome,time,cost | latent state, action, horizon)."""
    slow, fast = divmod(state, 2)
    if action < 2:
        success = (0.94 if action == slow else 0.12) - 0.12 * fast
    elif action == 2:
        success = 0.91 - 0.05 * fast
    else:
        success = 0.67 - 0.12 * fast
    result = np.zeros((2, 4, 4))
    ti, ci = np.meshgrid(np.arange(4), np.arange(4), indexing="ij")
    for outcome in (0, 1):
        time_center = (0.25, 0.25, 1.1, 2.1)[action] + 0.6 * fast + 0.1 * (horizon - 1)
        time_center += 0.25 * (1 - outcome)
        cost_center = (0.15, 0.15, 1.8, 0.6)[action] + 0.35 * fast + 0.3 * ti
        cost_center += 0.25 * (1 - outcome)
        weights = np.exp(
            -1.25 * (ti - time_center) ** 2 - 1.25 * (ci - cost_center) ** 2
        )
        result[outcome] = (
            weights / weights.sum() * (success if outcome else 1 - success)
        )
    return result.reshape(-1)


def preparation_overhead(horizon):
    """Known prefix of an option: prepare, then dispatch the terminal tool."""
    if horizon not in HORIZONS:
        raise ValueError("unsupported preparation option")
    ticks = horizon - 1
    return ticks, 0.1 * ticks


def joint_table():
    """Marginalize preparation dynamics; predict residual terminal-tool T/C.

    These are fixed open-loop preparation options, not learned skills or an
    autoregressive neural rollout. Evaluation adds their known time and cost.
    """
    result = np.empty((len(HORIZONS), 4, 4, len(JOINT_SUPPORT)))
    for hi, horizon in enumerate(HORIZONS):
        for action in range(4):
            dynamics = transition(2 if action == 2 else 0)
            future = np.linalg.matrix_power(dynamics, horizon - 1)
            terminal = np.array(
                [conditional_joint(s, action, horizon) for s in range(4)]
            )
            result[hi, action] = future @ terminal
    return result


def query_vector(action, horizon_index):
    result = np.zeros(ACTION_DIM)
    result[action] = 1
    result[4 + horizon_index] = 1
    return result


def coarsen_label(joint_class, rng, receipt_id, launch_at):
    """Registered ignorable observation mechanism; no missing-ACK survival claim.

    A randomly selected status query right-censors only when it actually proves
    nonoccurrence. A lost ACK is independent of outcome in this controlled pilot.
    Real missing-not-at-random records need an observation model or sensitivity
    analysis and cannot silently use this likelihood assumption.
    """
    outcome, elapsed, cost = map(int, JOINT_SUPPORT[joint_class])
    choice = rng.random()
    if launch_at < 0 or not np.isfinite(launch_at):
        raise ValueError("invalid tool launch time")
    common = {
        "source": "simulator",
        "observed_at": float(launch_at + elapsed + 3),
        "confirmed_cost_lower_bound": 1.0,
    }
    if choice < 0.15:
        status = "receipt_missing" if choice < 0.08 else "cancel_requested"
        evidence = Evidence(**common, observation_status=status)
    elif choice < 0.45:
        cutoff = int(rng.choice([2, 4]))
        if elapsed > cutoff:
            common["observed_at"] = float(launch_at + cutoff)
            evidence = Evidence(
                **common,
                observation_status="verified_ongoing",
                time_kind="right_censored",
                time_lower=float(cutoff),
                nonoccurrence_witness=receipt_id,
            )
        else:
            evidence = Evidence(
                **common,
                observation_status="terminal",
                outcome=outcome,
                time_kind="exact",
                time_lower=float(elapsed),
                time_upper=float(elapsed),
                final_cost=float(cost),
                receipt_ref=receipt_id,
            )
    elif choice < 0.65:
        lo, hi = (0.0, 2.0) if elapsed <= 2 else (2.0, 8.0)
        evidence = Evidence(
            **common,
            observation_status="terminal",
            outcome=outcome,
            time_kind="interval",
            time_lower=lo,
            time_upper=hi,
            final_cost=float(cost),
            receipt_ref=receipt_id,
        )
    else:
        evidence = Evidence(
            **common,
            observation_status="terminal",
            outcome=outcome,
            time_kind="exact",
            time_lower=float(elapsed),
            time_upper=float(elapsed),
            final_cost=float(cost),
            receipt_ref=receipt_id,
        )
    return evidence


def generate_dataset(count, seed, split, length=16):
    if not 1 <= count <= 100_000 or not 4 <= length <= 256:
        raise ValueError("dataset size outside registered bounds")
    split_id = {"train": 11, "dev": 23, "confirm": 37, "pilot": 41}[split]
    table = joint_table()
    xs, queries, masks, groups, truth, realized, sampled = [], [], [], [], [], [], []
    legal, deadlines, budgets, costs, counts = [], [], [], [], {}
    for i in range(count):
        rng = np.random.default_rng(np.random.SeedSequence([seed, split_id, i]))
        state = int(rng.integers(4))
        actions = tuple(map(int, rng.integers(3, size=length)))
        events = [
            SensorEvent(
                0,
                int(rng.integers(3)),
                0,
                state // 2 if rng.random() < 0.92 else 1 - state // 2,
            )
        ]
        for t in range(length):
            if t:
                state = int(rng.choice(4, p=transition(actions[t])[state]))
            if rng.random() < 0.7:
                events.append(
                    SensorEvent(
                        t,
                        t + int(rng.integers(4)),
                        1,
                        state % 2 if rng.random() < 0.84 else 1 - state % 2,
                    )
                )
        history = PublicHistory(actions, tuple(events))
        x = encode_history(history, length - 1)
        posterior = bayes_belief(history, length - 1)
        distribution = np.einsum("s,hask->hak", posterior, table)
        actual = table[:, :, state]
        # Common random numbers across models, and across action alternatives.
        uniforms = rng.random(len(HORIZONS))
        outcome_classes = (actual.cumsum(axis=-1) < uniforms[:, None, None]).sum(
            axis=-1
        )
        outcome_classes = np.minimum(outcome_classes, len(JOINT_SUPPORT) - 1)
        action_mask = np.ones(4, dtype=bool)
        if rng.random() < 0.3:
            action_mask[int(rng.integers(4))] = False
        a = int(rng.choice(np.flatnonzero(action_mask)))
        h = int(rng.integers(len(HORIZONS)))
        group = f"{SCHEMA}:{seed}:{split}:{i}"
        event_class = int(outcome_classes[h, a])
        wait, _ = preparation_overhead(HORIZONS[h])
        evidence = coarsen_label(event_class, rng, f"simulator:{group}", length + wait)
        mask = allowed_mask(evidence)
        if not mask[event_class]:
            raise AssertionError("coarsening excluded the realized event")
        counts[evidence.observation_status.value + "/" + evidence.time_kind.value] = (
            counts.get(
                evidence.observation_status.value + "/" + evidence.time_kind.value, 0
            )
            + 1
        )
        # Full environment cost includes every history step and delivered readback.
        prefix = 0.1 * length + 0.05 * sum(e.observed_at < length for e in events)
        xs.append(x)
        queries.append(query_vector(a, h))
        masks.append(mask)
        groups.append(group)
        truth.append(distribution)
        realized.append(outcome_classes)
        sampled.append(event_class)
        legal.append(action_mask)
        deadlines.append(float(rng.choice([4, 8])))
        budgets.append(float(rng.choice([2, 4, 8])))
        costs.append(prefix)
    return Dataset(
        np.array(xs),
        np.array(queries),
        np.array(masks),
        tuple(groups),
        np.array(legal),
        np.array(deadlines),
        np.array(budgets),
        np.array(costs),
        counts,
        EvaluatorOnly(np.array(truth), np.array(realized), np.array(sampled)),
    )
