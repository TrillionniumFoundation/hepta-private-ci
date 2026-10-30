"""Population NDU score learning and conditional exponential-moment critics.

Evaluation always uses gamma=2 and -log(E exp(-2 R))/2, with R obtained from
actual codec readback minus all measured costs. The risk training objective is
E[(exp(-2 R)-1)/2]. Its minimizers equal the population CE maximizers; its
un-normalized score gradient avoids the biased finite-batch ratio estimator.
The gamma=0 arm instead minimizes -E[R] and is explicitly a mean control.

The estimator covers parameter dependence through the declared stochastic law.
Every sampled action, Gaussian emission latent and text categorical outcome
contributes its score exactly once. Samples are held fixed in log_prob. All
deterministic parameter-dependent paths leading to those laws retain their
graph. Readback returns are detached; adding a pathwise derivative through the
same sampled emission would double count. Parameter-dependent rewards outside
that law require a separate direct derivative, not this estimator.

No LAX approximation, return clipping, self-normalized risk gradient, or
supervised auxiliary objective is hidden here. A caller's supervised weight and
optimizer gradient clipping must be reported separately.
"""

import math

import torch
from torch import Tensor


EVALUATION_GAMMA = 2.0


def _vector(value, name):
    if not torch.is_tensor(value) or value.dtype not in (torch.float32, torch.float64):
        raise ValueError(f"{name} must be a float32/float64 tensor")
    if value.ndim == 0:
        value = value.reshape(1)
    if value.ndim != 1 or value.numel() == 0 or not bool(torch.isfinite(value).all()):
        raise ValueError(f"{name} must be a finite nonempty vector")
    return value


def _observed(value, reference, name):
    result = torch.as_tensor(value, dtype=reference.dtype, device=reference.device).detach()
    result = _vector(result, name)
    if result.shape != reference.shape:
        raise ValueError(f"{name} must align with the score/prediction vector")
    return result


def _gamma(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (0.0, 2.0):
        raise ValueError("Use gamma=2 for the frozen risk objective or gamma=0 for the mean control")
    return float(value)


def _moment_cost(returns, gamma):
    result = -returns if gamma == 0 else torch.expm1(-gamma * returns) / gamma
    if not bool(torch.isfinite(result).all()):
        raise ValueError("Observed exponential moment exceeds the supported numeric domain; no clipping applied")
    return result


def moment_score_terms(joint_log_prob_sums, net_returns, *, gamma=2.0, baseline=None):
    """Per-trajectory score terms for a fixed external actual-return objective.

Use their mean for IID sampled trajectories. Exact-law tests may instead sum
them against detached true probability masses. A baseline must be independent
of that trajectory's random choices, conditional on the public task context.
The caller must never pass a return-dependent self baseline here.
"""
    scores = _vector(joint_log_prob_sums, "Joint log probabilities")
    returns = _observed(net_returns, scores, "Actual net returns")
    coefficient = _moment_cost(returns, _gamma(gamma))
    if baseline is not None:
        coefficient = coefficient - _observed(baseline, scores, "Independent baseline")
    return coefficient.detach() * scores


def population_metrics(net_returns):
    """Fixed-gamma plug-in evaluation; its logarithm has finite-sample bias."""
    if not torch.is_tensor(net_returns):
        net_returns = torch.as_tensor(net_returns, dtype=torch.float64)
    values = _vector(net_returns, "Actual net returns").detach().to(torch.float64)
    log_moment = torch.logsumexp(-EVALUATION_GAMMA * values, dim=0) - math.log(len(values))
    return {
        "evaluation_gamma": EVALUATION_GAMMA,
        "population_ce_plugin": float(-log_moment / EVALUATION_GAMMA),
        "population_log_moment_plugin": float(log_moment),
        "mean_net_return": float(values.mean()),
        "sample_count": len(values),
        "aggregation": "population_log_after_mean_over_tasks_and_actual_draws",
        "ce_estimate_bias": "finite_sample_logmeanexp_plugin; not_an_unbiased_population_CE",
    }


def actor_score_loss(joint_log_prob_sums, net_returns, *, gamma=2.0,
                     baseline="leave_one_out", independent_episodes=False):
    """Return (minimization loss, detached metadata) for actual joint scores.

With independent episodes, leave-one-out uses only other draws' moment costs
and is an unbiased baseline. A singleton uses zero. Correlated/common-noise
draws within an update must use baseline='none', or a separately qualified
independent baseline. Paired randomness across comparison arms is compatible
when each individual arm's batch episodes are independent.

The statistical gradient is unbiased before clipping/optimizer processing,
under a complete correct score law and parameter-independent external reward.
It is not a finite-batch unbiased gradient of the normalized CE value itself.
"""
    scores = _vector(joint_log_prob_sums, "Joint log probabilities")
    returns = _observed(net_returns, scores, "Actual net returns")
    gamma = _gamma(gamma)
    costs = _moment_cost(returns, gamma)
    if baseline not in {"none", "leave_one_out"}:
        raise ValueError("Unknown baseline; self-normalized or same-draw baselines are unsupported")
    if baseline == "leave_one_out" and len(scores) > 1:
        if independent_episodes is not True:
            raise ValueError("Leave-one-out requires independent episode draws within the update")
        baseline_values = (costs.sum() - costs) / (len(scores) - 1)
        used = "independent_episode_leave_one_out"
    else:
        baseline_values = torch.zeros_like(costs)
        used = "zero_singleton" if baseline == "leave_one_out" else "zero"
    loss = moment_score_terms(scores, returns, gamma=gamma, baseline=baseline_values).mean()
    stats = {
        **population_metrics(returns),
        "training_gamma": gamma,
        "training_objective": "negative_mean_return" if gamma == 0 else "mean_expm1_negative_gamma_return_over_gamma",
        "moment_objective_estimate": float(costs.mean()),
        "score_estimator": "unbiased_unnormalized_moment_score_under_declared_sampling_conditions",
        "baseline": used,
        "self_normalized_risk_gradient": False,
        "supervised_loss_included": False,
        "has_score_graph": bool(scores.requires_grad),
    }
    return loss, stats


def actual_suffix_returns(terminal_utility, cost_increments):
    """Terminal observed utility minus costs from each registered event onward.

For one episode, entry k is the target at the boundary before cost event k.
Attach encoding and final emission/readback costs to their explicit events
once. Whether already incurred encoding is part of event zero is an origin
convention that must be shared by the runtime state and this supplied ledger.
"""
    costs = cost_increments if torch.is_tensor(cost_increments) else torch.as_tensor(cost_increments, dtype=torch.float64)
    costs = _vector(costs, "Actual incremental costs").detach()
    if bool((costs < 0).any()):
        raise ValueError("Actual incremental costs cannot be negative")
    terminal = torch.as_tensor(terminal_utility, dtype=costs.dtype, device=costs.device).detach()
    if terminal.numel() != 1 or not bool(torch.isfinite(terminal).all()):
        raise ValueError("One finite independent terminal utility is required")
    remaining = costs.flip(0).cumsum(0).flip(0)
    return terminal.reshape(()) - remaining


def critic_log_moment_loss(log_moment_predictions, suffix_returns, *, gamma=2.0):
    """Return a proper conditional-moment loss and detached diagnostics.

The caller computes predictions as critic(features.detach()), so critic
fitting cannot alter the generator representation through its inputs. For
Y=exp(-gamma * actual_suffix_return), exp(v)-Y*v is minimized conditionally at
v=log E[Y|public pre-action state]. Regressing log Y instead would target
E[log Y|state], a different quantity. No target clipping is performed.

For the gamma=0 mean-control arm this log-moment is identically zero. It is
not relabeled as a mean-return critic; the actor uses its independent baseline.
"""
    prediction = _vector(log_moment_predictions, "Conditional log-moment predictions")
    returns = _observed(suffix_returns, prediction, "Actual suffix returns")
    gamma = _gamma(gamma)
    target = torch.exp(-gamma * returns)
    predicted_moment = prediction.exp()
    if not bool(torch.isfinite(target).all()) or not bool(torch.isfinite(predicted_moment).all()):
        raise ValueError("Conditional exponential moment overflow; no clipping applied")
    loss = (predicted_moment - target * prediction).mean()
    if not bool(torch.isfinite(loss)):
        raise ValueError("Conditional moment loss is outside the numeric domain")
    return loss, {
        "critic_target": "log_conditional_expectation_of_actual_suffix_exponential_moment",
        "critic_loss": "mean(exp(v)-exp(-gamma*R_suffix)*v)",
        "gamma": gamma,
        "samples": len(prediction),
        "target_moment_mean": float(target.mean()),
        "predicted_moment_mean": float(predicted_moment.detach().mean()),
        "target_log_sample_regression": False,
        "requires_detached_input_features": True,
    }
