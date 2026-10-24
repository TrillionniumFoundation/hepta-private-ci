"""Bounded internal generation control, with no outcome label in runtime APIs."""

from dataclasses import dataclass
import math

from .forecast import CONTINUATIONS, certainty_equivalent


POLICIES = ("static", "router", "risk_neutral", "ndu", "allocation_only", "static_pool")


def legal_indices(step_count, content_control, remaining=2):
    return tuple(index for index, plan in enumerate(CONTINUATIONS)
                 if len(plan) <= min(remaining, 4 - step_count)
                 and (content_control or all(action in {"refine_image", "refine_text"} for action in plan)))


def choose_plan(scores, step_count, content_control, remaining=2, penalty=.002):
    candidates = legal_indices(step_count, content_control, remaining)
    if not candidates or any(not math.isfinite(float(scores[index])) for index in candidates):
        raise ValueError("Invalid bounded action-value candidates")
    # Stable ties favor fewer actual steps, then the fixed catalogue order.
    choice = max(candidates, key=lambda i: (float(scores[i]) - penalty * len(CONTINUATIONS[i]),
                                            -len(CONTINUATIONS[i]), -i))
    return CONTINUATIONS[choice]


@dataclass(frozen=True)
class ControlResult:
    state: object
    actions: tuple[str, ...]
    forecasts: int
    simulated_actions: int
    executed_actions: int
    predicted_objectives: tuple[float, ...]


def control(snapshot, forecast, observation, initial, policy, *, static_plan=(), penalty=.002):
    """Amortized two-step replanning; native enumerative MPC is a separate policy.

    static_pool spends real work on stop-now and a dev-fixed continuation. It
    selects with the same public forecast; unused budget is never called work.
    """
    if policy not in POLICIES or snapshot.fingerprint != forecast.snapshot_digest:
        raise ValueError("Unregistered policy or mismatched forecast")
    if policy == "allocation_only" and initial.content_control:
        raise ValueError("Allocation ablation must bypass the initial content gate")
    if tuple(static_plan) not in CONTINUATIONS:
        raise ValueError("Static continuation outside the registered family")
    if policy == "static":
        state = initial
        for action in static_plan:
            state = snapshot.step(state, action)
        return ControlResult(state, tuple(static_plan), 0, 0, len(static_plan), ())
    binding = forecast.bind_observation(observation)
    state, actions, forecasts, predicted = initial, [], 0, []
    if policy == "static_pool":
        candidate = initial
        for action in static_plan:
            candidate = snapshot.step(candidate, action)
        v0, p0 = forecast.all_plan_distributions_bound(initial, binding)
        v1, p1 = forecast.all_plan_distributions_bound(candidate, binding)
        first = float(certainty_equivalent(v0, p0[0, 0], 0))
        second = float(certainty_equivalent(v1, p1[0, 0], 0)) - penalty * len(static_plan)
        take_candidate = second > first
        return ControlResult(candidate if take_candidate else initial,
                             tuple(static_plan) if take_candidate else (), 2, len(static_plan),
                             0, (first, second))
    gamma = 0. if policy in {"router", "risk_neutral"} else 2.
    while len(actions) < 2:
        values, probabilities = forecast.all_plan_distributions_bound(state, binding)
        scores = certainty_equivalent(values, probabilities[0], gamma)
        forecasts += 1
        plan = choose_plan(scores, state.step_count, state.content_control, 2 - len(actions), penalty)
        predicted.append(float(scores[CONTINUATIONS.index(plan)]) - penalty * len(plan))
        if not plan:
            break
        if policy == "router":
            for action in plan:
                state = snapshot.step(state, action)
                actions.append(action)
            break
        state = snapshot.step(state, plan[0])
        actions.append(plan[0])
    return ControlResult(state, tuple(actions), forecasts, 0, len(actions), tuple(predicted))
