"""Differentiable finite NDU evaluator for the actual v4 generator state.

The forward algorithm mirrors joint_generation/planner.rs: all legal affordable
roots are materialized, remaining forecast calls are divided fairly, deeper
STOP is visited first, and exhausted branches use the continuation critic.
This is the fixed Mean-law, single-particle specialization. Risk is therefore
inactive; critics are model predictions, not external quality measurements.
"""

from dataclasses import dataclass, replace
import hashlib
import json

import torch

from scripts.joint_generation_v4_codecs import flush_mean
from scripts.joint_generation_v4_model import ACTIONS


@dataclass(frozen=True)
class FiniteProfile:
    risk: float = 0.25
    discount_per_second: float = 1.0
    latency_weight: float = 0.01
    horizon: int = 2
    max_forecasts: int = 32
    action_micros: tuple = (1000,) * 7

    def __post_init__(self):
        # This diagnostic exports one explicit profile, never silently changes
        # the Rust checkpoint metadata when the Python evaluator changes.
        if (
            self.risk != 0.25
            or self.discount_per_second != 1.0
            or self.latency_weight != 0.01
            or self.horizon != 2
            or self.max_forecasts != 32
            or self.action_micros != (1000,) * 7
        ):
            raise ValueError(
                "Only the exported finite v4 diagnostic profile is supported"
            )

    def edge(self, action, future):
        seconds = self.action_micros[action] / 1_000_000
        return (
            -self.latency_weight * seconds + self.discount_per_second**seconds * future
        )


@dataclass
class Plan:
    scores: torch.Tensor
    scored: tuple
    action: int
    forecasts: int
    exhausted: bool
    trace_sha256: str


class _Search:
    def __init__(self, generator, public, profile):
        self.generator, self.public, self.profile = generator, public, profile
        self.calls, self.limit, self.exhausted, self.trace = (
            0,
            profile.max_forecasts,
            False,
            [],
        )

    def forecast(self, state, observation, action):
        duration = self.profile.action_micros[action]
        if duration > observation.budget_remaining:
            return None
        if self.calls >= self.limit:
            self.exhausted = True
            return None
        self.calls += 1
        following = self.generator.advance(state, ACTIONS[action], self.public)
        observation = replace(
            observation, budget_remaining=observation.budget_remaining - duration
        )
        delta = b""
        if action == 6:
            following, observation, delta = flush_mean(
                self.generator, following, observation
            )
        self.trace.append(
            (
                state.steps,
                action,
                observation.budget_remaining,
                hashlib.sha256(delta).hexdigest(),
            )
        )
        return following, observation

    def value(self, state, observation, depth):
        inspection = self.generator.inspect(state, observation)
        if state.stopped:
            return inspection["delivery_critic"].sigmoid().reshape(())
        if depth == 0 or observation.budget_remaining == 0:
            return inspection["critic"].sigmoid().reshape(())
        legal = inspection["policy.legal_mask"].detach().flatten().bool().tolist()
        alternatives = []
        for action in (6, 0, 1, 2, 3, 4, 5):
            if not legal[action]:
                continue
            successor = self.forecast(state, observation, action)
            if successor is not None:
                alternatives.append(
                    (
                        action,
                        self.profile.edge(action, self.value(*successor, depth - 1)),
                    )
                )
        if not alternatives:
            return inspection["critic"].sigmoid().reshape(())
        chosen = max(alternatives, key=lambda item: float(item[1].detach()))
        self.trace.append(("value", depth, chosen[0]))
        return chosen[1]


def choose(generator, state, observation, public, profile=FiniteProfile()):
    """Return exact bounded scores with gradients to the supplied state.

    Callers choose whether generator parameters are frozen. Training freezes the
    reference; native parity uses the trained candidate's own full kernel.
    """
    inspection = generator.inspect(state, observation)
    legal = inspection["policy.legal_mask"].detach().flatten().bool().tolist()
    search = _Search(generator, public, profile)
    roots = []
    for action in range(7):
        if legal[action]:
            successor = search.forecast(state, observation, action)
            if successor is not None:
                roots.append((action, successor))
    if not roots:
        raise ValueError("No affordable legal action under admitted budget")
    remaining = profile.max_forecasts - search.calls
    scores = [state.shared.new_zeros(()) for _ in range(7)]
    scored = [False] * 7
    for index, (action, successor) in enumerate(roots):
        search.limit = (
            search.calls + remaining // len(roots) + int(index < remaining % len(roots))
        )
        scores[action] = profile.edge(
            action, search.value(*successor, profile.horizon - 1)
        )
        scored[action] = True
    selected = max(
        (index for index in range(7) if scored[index]),
        key=lambda index: float(scores[index].detach()),
    )
    search.trace.append(("root", selected))
    trace_sha256 = hashlib.sha256(
        json.dumps(search.trace, separators=(",", ":")).encode()
    ).hexdigest()
    return Plan(
        torch.stack(scores),
        tuple(scored),
        selected,
        search.calls,
        search.exhausted,
        trace_sha256,
    )


def live_state(generator, public):
    """One episode starts from zero memory; both content transitions stay live."""
    state = generator.encode(public)
    for action in ("shared", "text"):
        state = generator.advance(state, action, public)
    return state


def policy_improvement_loss(generator, state, observation, target_scores, scored):
    """Exact finite-action policy gradient for a fixed model-based Q target.

    Finite-difference checks MUST hold target_scores and scored fixed while varying
    the actor/encoder. Re-evaluating detached Q would check another derivative.
    """
    logits = generator.inspect(state, observation)["actor.logits"].flatten()
    mask = torch.tensor(scored, dtype=torch.bool, device=logits.device)
    probabilities = logits.masked_fill(~mask, -torch.inf).softmax(0)
    return -(probabilities * target_scores.detach()).sum()


def loss_terms(generator, frozen_reference, public, observation, target="Hepta🙂"):
    if any(parameter.requires_grad for parameter in frozen_reference.parameters()):
        raise ValueError("The NDU evaluator must be an explicitly frozen reference")
    state = live_state(generator, public)
    plan = choose(frozen_reference, state, observation, public)
    return {
        "recursive": -plan.scores[plan.action],
        "policy": policy_improvement_loss(
            generator, state, observation, plan.scores, plan.scored
        ),
        "teacher_forced": generator.text_loss(state, target)[0],
    }, plan
