"""Frozen-policy action values under an independent, actual finite task world.

The actor and planner determine actions; only the task world determines state
transitions, observation probabilities, terminal rewards and paid fees.  An
alpha vector contains expected net returns conditional on each possible latent
starting state.  No latent state or world posterior is sent to the actor.

Alpha vectors and their targets are stop-gradient data.  The auxiliary loss
below trains an estimator's posterior, including its recurrent history, to
retain state information relevant to the frozen deployed continuation policy.
It is policy evaluation supervision, not a policy-gradient or optimality claim.
"""

import copy

import numpy as np


def _clone_frozen_actor(actor):
    """Copy dynamic state within an already isolated inference snapshot.

    R14 ``step`` treats ``params`` and ``cell`` as fixed model data; only the
    cell's deterministic transition cache can grow. Share them inside this
    frozen tree, but deep-copy every other field, including arbitrary hidden
    containers. The original caller is isolated by a full deepcopy first.
    """
    memo = {id(getattr(actor, name)): getattr(actor, name)
            for name in ("params", "cell") if getattr(actor, name, None) is not None}
    return copy.deepcopy(actor, memo)


def encode(token, dt, reset=False):
    """Encode one public action outcome, without latent state, label or fee."""
    token = -1 if token is None else token
    if (isinstance(token, (bool, np.bool_))
            or not isinstance(token, (int, np.integer)) or not -1 <= token < 8
            or not np.isfinite(dt) or dt < 0 or (reset and token != -1)):
        raise ValueError("Invalid public observation")
    result = np.zeros(11, dtype=np.float64)
    if token >= 0:
        result[token] = 1.
        result[8] = 1.
    result[9], result[10] = float(dt), float(bool(reset))
    return result


def policy_alpha(world, actor, planner, schedule, budget):
    """Force each first action, then execute a frozen actual actor/planner.

    ``actor`` must be positioned at the intended causal prefix.  All branches
    preserve its complete hidden/current state by cloning.  The common planner
    may use a different fitted model from ``world``.  Horizons are deliberately
    restricted to three intervals for exact enumeration of this small profile.
    Returned vectors have shape ``(world.state_count,)`` and include all fees.
    """
    current = getattr(actor, "current", None)
    if current is None:
        raise ValueError("The actor must already be at its causal prefix")
    _, times, reads = planner._inputs(current, schedule, budget)
    if len(times) > 3:
        raise ValueError("Exact deployed-policy targets support at most three intervals")
    emissions, reset, reward, read_cost = (
        np.array(getattr(world, key), dtype=np.float64, copy=True)
        for key in ("E", "R", "reward", "read_cost")
    )
    states = planner.states
    if (emissions.shape != (states, 8) or reset.shape != (states, states)
            or reward.shape != (states, 2) or read_cost.shape != (states,)):
        raise ValueError("World and actor/planner dimensions differ")
    if not all(np.isfinite(x).all() for x in (emissions, reset, reward, read_cost)):
        raise ValueError("Nonfinite task data")
    for matrix in (emissions, reset):
        if matrix.min() < 0 or not np.allclose(matrix.sum(1), 1., rtol=0, atol=1e-11):
            raise ValueError("Task emissions and reset must be stochastic")
    reset_fee, time_price = float(world.reset_cost), float(world.latency_price)
    if (not np.isfinite([reset_fee, time_price]).all() or min(reset_fee, time_price) < 0
            or read_cost.min() < 0):
        raise ValueError("Task fees must be finite and nonnegative")
    transitions = {dt: np.array(world.transition(dt), dtype=np.float64, copy=True)
                   for dt in set(times)}
    for matrix in transitions.values():
        if (matrix.shape != (states, states) or not np.isfinite(matrix).all()
                or matrix.min() < -2e-12
                or not np.allclose(matrix.sum(1), 1., rtol=0, atol=2e-10)):
            raise ValueError("Invalid actual-world transition")

    def follow(estimator, remaining, remaining_reads):
        action = planner.choose(estimator.current, remaining, remaining_reads)
        return force(action, estimator, remaining, remaining_reads)

    def force(action, estimator, remaining, remaining_reads):
        if action not in planner.legal_actions(remaining, remaining_reads):
            raise ValueError("Continuation policy chose an illegal action")
        if action in ("STOP0", "STOP1"):
            return reward[:, int(action[-1])].copy()
        dt, rest = remaining[0], remaining[1:]
        transition = transitions[dt]
        if action == "READ":
            tail = np.zeros(states)
            for token in range(emissions.shape[1]):
                if np.any(emissions[:, token] > 0):
                    branch = _clone_frozen_actor(estimator)
                    branch.step(encode(token, dt))
                    tail += emissions[:, token] * follow(branch, rest, remaining_reads - 1)
            # The READ price is paid at the actual successor state.
            return transition @ (tail - read_cost) - time_price * dt
        branch = _clone_frozen_actor(estimator)
        branch.step(encode(-1, dt, action == "RESET"))
        tail = transition @ follow(branch, rest, remaining_reads)
        if action == "RESET":
            return reset @ tail - reset_fee - time_price * dt
        if action == "WAIT":
            return tail - time_price * dt
        raise ValueError("Unknown action")

    frozen = copy.deepcopy(actor)
    return {action: force(action, frozen, times, reads)
            for action in planner.legal_actions(times, reads)}


def loss_and_probability_gradient(probabilities, teacher, alpha, weight=1., action_mask=None):
    """Mean squared Q^pi error and gradient with respect to probabilities.

    ``probabilities`` and ``teacher`` have shape ``(..., states)``.  ``alpha``
    has shape ``(..., actions, states)`` and may broadcast over example axes.
    A legal-action mask may broadcast over ``(..., actions)``.  Teacher beliefs
    are training-only independent task-world posteriors at the same prefixes.
    The returned derivative includes the mean over all unmasked example/action
    entries.  Softmax estimators must apply the softmax Jacobian afterward.
    """
    p, target, vectors = map(lambda x: np.asarray(x, dtype=np.float64),
                             (probabilities, teacher, alpha))
    if (p.ndim < 1 or target.shape != p.shape or vectors.ndim < 2
            or vectors.shape[-1] != p.shape[-1] or vectors.shape[-2] == 0
            or not np.isfinite(weight) or weight < 0):
        raise ValueError("Invalid Q^pi loss dimensions or weight")
    for distribution in (p, target):
        if (not np.isfinite(distribution).all() or distribution.min() < 0
                or not np.allclose(distribution.sum(-1), 1., rtol=0, atol=1e-10)):
            raise ValueError("Q^pi supervision requires normalized distributions")
    if not np.isfinite(vectors).all():
        raise ValueError("Nonfinite Q^pi vectors")
    vectors = np.broadcast_to(vectors, p.shape[:-1] + vectors.shape[-2:])
    difference = np.einsum("...i,...ai->...a", p - target, vectors)
    mask = np.ones_like(difference, dtype=bool) if action_mask is None else np.broadcast_to(
        np.asarray(action_mask, dtype=bool), difference.shape)
    count = int(np.count_nonzero(mask))
    if count == 0:
        raise ValueError("At least one legal Q^pi target is required")
    difference = np.where(mask, difference, 0.)
    loss = float(weight * np.sum(difference * difference) / count)
    gradient = 2 * weight / count * np.einsum("...a,...ai->...i", difference, vectors)
    return loss, gradient


def cost_sensitive_weights(target_q, legal, temperature=.1):
    """Fixed legal-action weights from actual net Q^pi, never differentiated.

    Each prefix has total weight equal to its number of legal actions, keeping
    the original per-prefix mass in the weighted squared-error objective.
    Low temperature concentrates on the highest-net-value legal action; large
    temperature approaches unit weight for every legal action. Known action
    fees can change these weights even when they are state-independent offsets.
    """
    q, supplied_mask = np.asarray(target_q, dtype=float), np.asarray(legal)
    if (q.ndim < 1 or q.shape[-1] == 0 or not np.isfinite(q).all()
            or not np.isscalar(temperature) or not np.isfinite(temperature)
            or temperature <= 0):
        raise ValueError("Finite Q targets and positive finite temperature are required")
    if (supplied_mask.dtype.kind not in "biuf" or not np.isfinite(supplied_mask).all()
            or np.any((supplied_mask != 0) & (supplied_mask != 1))):
        raise ValueError("Legal-action mask must be finite and binary")
    mask = np.broadcast_to(supplied_mask.astype(bool), q.shape)
    counts = mask.sum(axis=-1, keepdims=True)
    if np.any(counts == 0):
        raise ValueError("Every prefix needs a legal action")
    values = np.where(mask, q, -np.inf)
    with np.errstate(over="ignore", under="ignore"):
        exponential = np.exp((values - np.max(values, axis=-1, keepdims=True)) / temperature)
    return exponential / exponential.sum(axis=-1, keepdims=True) * counts


def monte_carlo_qpi(world, actor, planner, belief, schedule, budget, draws=2048, seed=72911):
    """Independent owner rollouts verifying conditional returns and actual fees.

    Each action has an independent seeded stream; these are Monte Carlo checks,
    not paired efficacy confirmation. ``world.sample_step`` executes and charges
    the actual task. Only its public raw symbol, duration and reset flag enter
    the cloned actor. The supplied world belief remains evaluator-only data.
    """
    p, times, reads = planner._inputs(belief, schedule, budget)
    planner._inputs(actor.current, times, reads)
    if isinstance(draws, bool) or not isinstance(draws, (int, np.integer)) or draws < 2:
        raise ValueError("At least two owner rollouts are required")
    frozen = copy.deepcopy(actor)
    rows = {}
    for action_index, first_action in enumerate(planner.legal_actions(times, reads)):
        rng = np.random.default_rng(seed + 104729 * action_index)
        utility, fees, rewards = np.empty(draws), np.empty(draws), np.empty(draws)
        for index in range(draws):
            estimator = _clone_frozen_actor(frozen)
            state = int(rng.choice(len(p), p=p))
            remaining, remaining_reads, action = times, reads, first_action
            paid = 0.
            while True:
                if action not in planner.legal_actions(remaining, remaining_reads):
                    raise ValueError("Owner received an illegal policy action")
                dt = 0. if action.startswith("STOP") else remaining[0]
                state, token, reward, fee = world.sample_step(state, action, dt, rng)
                paid += fee
                if action.startswith("STOP"):
                    utility[index], fees[index], rewards[index] = reward - paid, paid, reward
                    break
                estimator.step(encode(token, dt, action == "RESET"))
                remaining = remaining[1:]
                remaining_reads -= int(action == "READ")
                action = planner.choose(estimator.current, remaining, remaining_reads)
        rows[first_action] = dict(mean=float(utility.mean()),
                                  standard_error=float(utility.std(ddof=1) / np.sqrt(draws)),
                                  mean_fee=float(fees.mean()), mean_reward=float(rewards.mean()),
                                  draws=int(draws), seed=int(seed + 104729 * action_index))
    return rows
