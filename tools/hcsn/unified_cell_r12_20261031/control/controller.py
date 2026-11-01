"""Common finite-horizon controller with explicit observation marginalization."""

from typing import NamedTuple

import numpy as np


class PlanResult(NamedTuple):
    """Tuple-compatible result; columns are answer0, answer1, wait, read."""

    action: np.ndarray
    value: np.ndarray
    qvalues: np.ndarray


def _checked(beliefs, transition, emission, rewards, read_cost, horizon, budget,
             time_cost, dt):
    arrays = [np.asarray(x, dtype=np.float64) for x in
              (beliefs, transition, emission, rewards, read_cost)]
    p, kernel, likelihood, answer, cost = arrays
    if p.ndim != 2 or p.shape[1] == 0:
        raise ValueError("beliefs must have shape [batch, states]")
    n = p.shape[1]
    if kernel.shape != (n, n) or likelihood.shape != (n, 7):
        raise ValueError("P must be [states, states] and emission [states, 7]")
    if answer.shape != (n, 2) or cost.shape != (n,):
        raise ValueError("answer_rewards must be [states, 2], read_cost [states]")
    if not all(np.isfinite(x).all() for x in arrays):
        raise ValueError("model and belief entries must be finite")
    for name, probabilities in (("beliefs", p), ("P", kernel), ("emission", likelihood)):
        if np.any(probabilities < 0) or not np.allclose(
                probabilities.sum(axis=1), 1, atol=1e-10, rtol=0):
            raise ValueError(f"{name} must have nonnegative entries and unit row sums")
    if (isinstance(horizon, (bool, np.bool_)) or not isinstance(horizon, (int, np.integer))
            or horizon < 1):
        raise ValueError("horizon must be a positive integer")
    if (isinstance(budget, (bool, np.bool_)) or not isinstance(budget, (int, np.integer))
            or budget < 0):
        raise ValueError("budget must be a nonnegative integer")
    if not np.isfinite(dt) or dt < 0 or not np.isfinite(time_cost) or time_cost < 0:
        raise ValueError("dt and time_cost must be finite and nonnegative")
    return (*arrays, int(horizon), int(budget), float(time_cost) * float(dt))


def _result(qvalues):
    action = np.argmax(qvalues, axis=1)
    return PlanResult(action, qvalues[np.arange(len(action)), action], qvalues)


def _solve(p, kernel, likelihood, answer, cost, horizon, budget, tick_cost):
    qvalues = np.full((len(p), 4), -np.inf)
    qvalues[:, :2] = p @ answer
    if horizon == 1:
        return _result(qvalues)
    predicted = p @ kernel
    qvalues[:, 2] = -tick_cost + _solve(
        predicted, kernel, likelihood, answer, cost,
        horizon - 1, budget, tick_cost).value
    if budget:
        # [batch, observation, state], using hypothetical likelihood branches only.
        joint = predicted[:, None, :] * likelihood.T[None, :, :]
        evidence = joint.sum(axis=2)
        positive = evidence > 0
        branch_values = np.zeros_like(evidence)
        if positive.any():
            posteriors = joint[positive] / evidence[positive, None]
            branch_values[positive] = _solve(
                posteriors, kernel, likelihood, answer, cost,
                horizon - 1, budget - 1, tick_cost).value
        qvalues[:, 3] = (-tick_cost - predicted @ cost
                         + (evidence * branch_values).sum(axis=1))
    return _result(qvalues)


def plan(beliefs, P, emission, answer_rewards, read_cost, horizon=3, budget=2,
         time_cost=0.01, dt=1.0):
    """Plan from causal beliefs; P already represents one interval of length dt.

    ANSWER terminates now. WAIT predicts once and pays time_cost*dt. READ predicts
    once, pays the predicted state's expected read_cost plus time, and conditions
    on each of the seven possible observations. At horizon=1 only ANSWER is legal.
    The controller never accepts or inspects actual future observations. Zero-mass
    hypothetical branches are omitted exactly; no evidence floor is introduced.
    Tie-breaking uses the lowest action index. No continuous-belief cache is used.
    """
    return _solve(*_checked(beliefs, P, emission, answer_rewards, read_cost,
                           horizon, budget, time_cost, dt))


def plan_mc(beliefs, P, emission, answer_rewards, read_cost, horizon=3, budget=2,
            time_cost=0.01, dt=1.0, mc_samples=32, rng=None):
    """Sample the root READ observation marginal, with exact downstream planning.

    P, likelihoods, rewards, and predicted expected costs match plan(). Each root
    READ Q estimate is unbiased conditional on this model and belief. The selected
    max/action need not be unbiased. Downstream values are exact so the comparison
    isolates observation marginalization, not recursively compounded Monte Carlo
    max bias. This helper samples hypothetical outcomes, never an actual unused read.
    """
    args = _checked(beliefs, P, emission, answer_rewards, read_cost,
                    horizon, budget, time_cost, dt)
    p, kernel, likelihood, answer, cost, horizon, budget, tick_cost = args
    if (isinstance(mc_samples, (bool, np.bool_))
            or not isinstance(mc_samples, (int, np.integer)) or mc_samples < 1):
        raise ValueError("mc_samples must be a positive integer")
    if horizon == 1 or budget == 0:
        return _solve(*args)
    rng = np.random.default_rng() if rng is None else rng
    qvalues = np.full((len(p), 4), -np.inf)
    qvalues[:, :2] = p @ answer
    predicted = p @ kernel
    qvalues[:, 2] = -tick_cost + _solve(
        predicted, kernel, likelihood, answer, cost,
        horizon - 1, budget, tick_cost).value
    evidence = predicted @ likelihood
    cumulative = np.cumsum(evidence, axis=1)
    # Scale categorical draws by the computed total and stay strictly below it.
    # This avoids assigning roundoff mass to trailing zero-likelihood categories.
    totals = cumulative[:, -1, None]
    draws = np.minimum(rng.random((len(p), mc_samples)) * totals,
                       np.nextafter(totals, 0.0))
    observations = (draws[:, :, None] >= cumulative[:, None, :]).sum(axis=2)
    selected_likelihoods = likelihood.T[observations]
    joint = predicted[:, None, :] * selected_likelihoods
    normalizers = joint.sum(axis=2)
    if np.any(normalizers <= 0):
        raise FloatingPointError("categorical draw selected zero-evidence branch")
    posteriors = (joint / normalizers[:, :, None]).reshape(-1, p.shape[1])
    sampled_values = _solve(posteriors, kernel, likelihood, answer, cost,
                            horizon - 1, budget - 1, tick_cost).value
    qvalues[:, 3] = (-tick_cost - predicted @ cost
                     + sampled_values.reshape(len(p), mc_samples).mean(axis=1))
    return _result(qvalues)


def marginalization_diagnostics(beliefs, P, emission, answer_rewards, read_cost,
                               horizon=3, budget=2, time_cost=0.01, dt=1.0,
                               mc_samples=32, repetitions=64, seed=20261031):
    """Frozen-belief mechanism diagnostics; no data generation or tuning."""
    if repetitions < 2:
        raise ValueError("at least two repetitions are required for variance")
    args = (beliefs, P, emission, answer_rewards, read_cost)
    kwargs = dict(horizon=horizon, budget=budget, time_cost=time_cost, dt=dt)
    exact = plan(*args, **kwargs)
    rng = np.random.default_rng(seed)
    trials = [plan_mc(*args, **kwargs, mc_samples=mc_samples, rng=rng)
              for _ in range(repetitions)]
    actions = np.stack([trial.action for trial in trials])
    qvalues = np.stack([trial.qvalues for trial in trials])
    chosen_values = exact.qvalues[np.arange(len(exact.action))[None, :], actions]
    regrets = exact.value[None, :] - chosen_values
    finite = np.isfinite(exact.qvalues)
    error = np.zeros_like(qvalues)
    np.subtract(qvalues, exact.qvalues[None], out=error,
                where=np.broadcast_to(finite, qvalues.shape))
    rank_disagreements, rank_comparisons = 0, 0
    for a in range(4):
        for b in range(a + 1, 4):
            valid = finite[:, a] & finite[:, b]
            expected = np.sign(exact.qvalues[valid, a] - exact.qvalues[valid, b])
            sampled = np.sign(qvalues[:, valid, a] - qvalues[:, valid, b])
            rank_disagreements += int((sampled != expected).sum())
            rank_comparisons += sampled.size
    read_valid = finite[:, 3]
    return {"scope": "Fixed-belief mechanism check, not task confirmation.",
        "seed": seed, "mc_samples": mc_samples, "repetitions": repetitions,
        "beliefs": np.asarray(beliefs).tolist(), "exact_qvalues": [
            [float(x) if np.isfinite(x) else None for x in row] for row in exact.qvalues],
        "exact_actions": exact.action.tolist(),
        "sampled_actions": actions.tolist(),
        "sampled_read_qvalues": qvalues[:, read_valid, 3].tolist(),
        "read_q_variance": qvalues[:, read_valid, 3].var(axis=0, ddof=1).tolist(),
        "read_q_mean_error": error[:, read_valid, 3].mean(axis=0).tolist(),
        "action_disagreement_rate": float((actions != exact.action[None]).mean()),
        "pairwise_rank_disagreement_rate": rank_disagreements / max(1, rank_comparisons),
        "mean_exact_model_action_regret": float(regrets.mean()),
        "maximum_exact_model_action_regret": float(regrets.max()),
        "sampling_scope": "Root READ observation marginal; exact conditional continuation."}
