"""Qualification-only three-factor credit/feedback microbenchmark.

A held-out contextual bandit with one observed context, two legal actions and
environment-private target signs. No production model or source ledger writes.
"""
from dataclasses import dataclass
import math
import random
import statistics

ENVIRONMENT_SIGNS = (1, -1, 1)
ROUTES = ("routed", "context_gradient", "random", "shuffled", "broadcast")
TRACES = ("event_id", "latest")


def sigmoid(z):
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    x = math.exp(z)
    return x / (1 + x)


@dataclass(frozen=True)
class Event:
    step: int
    due: int
    group: int
    cue: int
    action: int
    action_probability: float
    reward: int

    def eligibility(self):
        return ((1.0 if self.action == 1 else 0.0)
                - self.action_probability) * self.cue


def run_credit(seed, routing="routed", trace="event_id", delay=0,
               feedback_density=0.35, steps=384):
    if routing not in ROUTES or trace not in TRACES:
        raise ValueError("unknown credit experiment arm")
    if not (0 <= delay <= 64 and 0 < feedback_density <= 1.0 and steps > 0):
        raise ValueError("invalid feedback profile")

    world = random.Random(100000 + seed)
    exploration = random.Random(200000 + seed)
    random_route = random.Random(300000 + seed)
    candidate_weights = [0.0] * len(ENVIRONMENT_SIGNS)
    pending = []
    latest = None
    observed_feedback = 0
    parameter_updates = 0

    for t in range(steps + delay + 1):
        if t < steps:
            group = world.randrange(len(ENVIRONMENT_SIGNS))
            cue = 1 if world.randrange(2) else -1
            probability = sigmoid(candidate_weights[group] * cue)
            action = 1 if exploration.random() < probability else -1
            # The target sign is private to the environment; the learner only
            # receives scalar reward when the scheduled feedback arrives.
            target = ENVIRONMENT_SIGNS[group] * cue
            reward = 1 if action == target else -1
            latest = Event(t, t + delay, group, cue, action, probability, reward)
            if world.random() < feedback_density:
                pending.append(latest)

        due = [e for e in pending if e.due == t]
        pending = [e for e in pending if e.due != t]
        for event in due:
            sample = event if trace == "event_id" else latest
            if sample is None:
                raise AssertionError("no eligibility for observed feedback")

            if routing in ("routed", "context_gradient"):
                destinations = (sample.group,)
            elif routing == "random":
                destinations = (random_route.randrange(len(candidate_weights)),)
            elif routing == "shuffled":
                destinations = ((sample.group + 1) % len(candidate_weights),)
            else:
                destinations = tuple(range(len(candidate_weights)))

            for destination in destinations:
                candidate_weights[destination] = max(-6, min(6,
                    candidate_weights[destination]
                    + 0.11 * event.reward * sample.eligibility()))
                parameter_updates += 1
            observed_feedback += 1

    if pending:
        raise AssertionError("feedback was discarded at the train horizon")

    heldout_probabilities = []
    for group, sign in enumerate(ENVIRONMENT_SIGNS):
        for cue in (-1, 1):
            p_positive = sigmoid(candidate_weights[group] * cue)
            heldout_probabilities.append(
                p_positive if cue * sign == 1 else 1 - p_positive)

    return {
        "heldout_accuracy": statistics.fmean(heldout_probabilities),
        "feedback_count": observed_feedback,
        "parameter_updates": parameter_updates,
        "candidate_weights": [round(w, 10) for w in candidate_weights],
        "status": "synthetic_candidate_only",
    }
