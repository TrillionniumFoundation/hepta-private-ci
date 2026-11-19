"""Model-based finite recursion and exact frozen-Q policy improvement.

The critic/world model parameters are frozen. Gradients through their inputs
are retained; tool execution, rubric labels and discrete feasibility masks are
not differentiated. This estimator is model-biased, truncated and piecewise
differentiable. It is not an unbiased environment policy-gradient estimator.
"""

import torch

from .controllers import ACTIONS
from .neural import forecast_tensors
from .objective import edge_value, forecast_seed


def torch_certainty_equivalent(values, probabilities, risk):
    # Accumulate the scalar backup in FP64 even for an FP32 neural core. This
    # retains the positive-risk limit without an underflowed FP32 divisor.
    values = values.to(torch.float64)
    probabilities = probabilities.to(torch.float64)
    probabilities = probabilities / probabilities.sum()
    mean = (values * probabilities).sum()
    if risk == 0:
        return mean
    positive = probabilities > 0
    values, probabilities = values[positive], probabilities[positive]
    centered = -risk * (values - mean)
    if bool(centered.abs().max() <= 1e-3):
        return mean - torch.log1p((probabilities * torch.expm1(centered)).sum()) / risk
    minimum = values.min()
    return (
        minimum
        - torch.logsumexp(probabilities.log() - risk * (values - minimum), 0) / risk
    )


def exact_policy_objective(logits, action_values):
    """Exact finite-action expectation; Q is a fixed improvement reference."""
    return (logits.softmax(0) * action_values.detach()).sum()


class DifferentiablePlanner:
    def __init__(self, reference, plan, seed):
        if any(parameter.requires_grad for parameter in reference.parameters()):
            raise ValueError("Recursive objective requires a frozen reference")
        self.reference, self.plan, self.seed = reference, plan, seed
        self.calls, self.exhausted = 0, False
        self.limit = plan.max_forecasts

    def terminal(self, state):
        return self.reference.utility_head(state).sigmoid().squeeze()

    def forecast(self, state, action, step, remaining, legal):
        if self.calls >= self.limit:
            self.exhausted = True
            return None
        self.calls += 1
        features, duration, following_legal = forecast_tensors(
            self.reference,
            state,
            action,
            self.plan.particles,
            forecast_seed(self.seed, step, action),
            step,
            remaining,
            legal,
            self.plan.memory_mode,
        )
        if not bool(torch.isfinite(duration)) or not bool(
            torch.isfinite(features).all()
        ):
            raise ValueError("Nonfinite recursive forecast")
        if bool(duration > remaining):
            return None
        return features, duration, following_legal

    def backup(self, predicted, step, remaining, depth):
        features, duration, legal = predicted
        following_budget = (remaining - duration).clamp(min=0)
        values = torch.stack(
            [
                edge_value(
                    duration,
                    self.value(x, step + 1, following_budget, legal, depth),
                    self.plan,
                )
                for x in features
            ]
        )
        return torch_certainty_equivalent(
            values, values.new_full(values.shape, 1 / len(values)), self.plan.risk
        )

    def value(self, state, step, remaining, legal, depth):
        candidates = [self.terminal(state)]
        if depth > 0 and bool(remaining > 0):
            for action in legal:
                if action != "STOP":
                    prediction = self.forecast(state, action, step, remaining, legal)
                    if prediction is not None:
                        candidates.append(
                            self.backup(prediction, step, remaining, depth - 1)
                        )
        return torch.stack(candidates).max()

    def action_values(self, state, *, step, remaining_seconds, legal_actions):
        self.calls, self.exhausted, self.limit = 0, False, self.plan.max_forecasts
        remaining = state.new_tensor(remaining_seconds)
        scores = {"STOP": self.terminal(state)}
        roots = [action for action in legal_actions if action != "STOP"]
        if remaining_seconds <= 0 or len(roots) > self.plan.max_forecasts:
            self.exhausted = bool(roots)
            return scores
        predictions = {
            action: self.forecast(state, action, step, remaining, legal_actions)
            for action in roots
        }
        extra = self.plan.max_forecasts - self.calls
        for index, action in enumerate(roots):
            if predictions[action] is not None:
                self.limit = (
                    self.calls
                    + extra // max(1, len(roots))
                    + int(index < extra % max(1, len(roots)))
                )
                scores[action] = self.backup(
                    predictions[action], step, remaining, self.plan.horizon - 1
                )
        return scores


def recursive_terms(model, reference, state, row, plan, seed):
    planner = DifferentiablePlanner(reference, plan, seed)
    scores = planner.action_values(
        state,
        step=row["episode_step"],
        remaining_seconds=row["remaining_seconds"],
        legal_actions=row["legal_actions"],
    )
    names = tuple(scores)
    values = torch.stack([scores[name] for name in names])
    logits = model.light_head(state)[[ACTIONS.index(name) for name in names]]
    # Unit coefficients are part of this training profile. Report both terms
    # separately; an auxiliary prediction gradient cannot satisfy their checks.
    return (
        -values.max(),
        -exact_policy_objective(logits, values),
        {
            "forecast_calls": planner.calls,
            "planner_budget_exhausted": planner.exhausted,
            "action_support": names,
        },
    )


def observed_states(model, groups, memory_mode, *, include_successors=True):
    """Unroll each whole episode separately; never keep state on the model."""
    result = []
    for sequence in groups:
        memory, states = None, []
        for row in sequence:
            current = model.public_state_step(
                row["features"], row["meta"], memory=memory, memory_mode=memory_mode
            )
            memory = current[3]
            states.append(current[:3])
        for index, (row, state) in enumerate(zip(sequence, states)):
            following = None
            if include_successors and row["next_features"] is not None:
                if memory_mode == "persistent":
                    if index + 1 >= len(states):
                        raise ValueError(
                            "Truncated persistent episode would reset its successor"
                        )
                    following = states[index + 1][0]
                else:
                    following = model.public_state(
                        row["next_features"], row["next_meta"]
                    )[0]
            result.append((row, state, following))
    return result
