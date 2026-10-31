"""A finite evidence task. Episode contains private facts; State contains public data."""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math

import numpy as np


ACTIONS = ("READ", "WAIT", "REPAIR", "STOP")
FEATURE_NAMES = (
    "posterior", "remaining_ticks_over_8", "remaining_budget_over_8",
    "ordinary_unread_over_3", "arrival_delay_over_8", "pending", "corrupt", "observed",
    "ordinary_reliability", "delayed_reliability", "corruption_probability",
    "read_budget_over_8", "repair_budget_over_8", "read_total_cost", "wait_total_cost",
    "repair_total_cost", "stop_total_cost", "invalid_attempt_cost",
)


@dataclass(frozen=True)
class TaskParameters:
    horizon: int = 6
    budget: int = 6
    ordinary_count: int = 3
    ordinary_reliability: float = 0.7
    delayed_reliability: float = 0.9
    arrival_tick: int = 2
    corruption_probability: float = 0.35
    read_budget: int = 2
    repair_budget: int = 1
    read_cost: float = 0.012
    wait_cost: float = 0.004
    repair_cost: float = 0.020
    stop_cost: float = 0.002
    latency_cost: float = 0.005
    invalid_attempt_cost: float = 0.030
    prior_probability: float = 0.5

    def __post_init__(self):
        if self.horizon < 1 or self.arrival_tick < 1 or self.ordinary_count < 0:
            raise ValueError("horizon/arrival must be positive; ordinary_count nonnegative")
        if min(self.budget, self.read_budget, self.repair_budget) < 0:
            raise ValueError("budgets must be nonnegative")
        if not (0.5 < self.ordinary_reliability < 1 and 0.5 < self.delayed_reliability < 1):
            raise ValueError("source reliabilities must be strictly between 0.5 and 1")
        if not 0 < self.prior_probability < 1 or not 0 <= self.corruption_probability <= 1:
            raise ValueError("invalid prior or corruption probability")
        costs = (self.read_cost, self.wait_cost, self.repair_cost, self.stop_cost,
                 self.latency_cost, self.invalid_attempt_cost)
        if any(not math.isfinite(x) or x < 0 for x in costs):
            raise ValueError("costs must be finite and nonnegative")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Episode:
    """Private evaluation fixture. Never pass this object to a policy/encoder."""
    seed: int
    parameters: TaskParameters
    truth: int
    ordinary_votes: tuple
    delayed_vote: int
    delayed_corrupt: bool

    def private_record(self):
        return asdict(self)


@dataclass(frozen=True)
class State:
    parameters: TaskParameters
    tick: int = 0
    remaining_budget: int = 6
    reads: int = 0
    vote_sum: int = 0
    delayed_status: str = "pending"
    delayed_vote: int = 0
    terminated: bool = False
    answer: int = 0
    total_cost: float = 0.0

    def __post_init__(self):
        p = self.parameters
        if not 0 <= self.tick <= p.horizon or (not self.terminated and self.tick >= p.horizon):
            raise ValueError("a live state must leave at least one submission tick")
        if not 0 <= self.remaining_budget <= p.budget or not 0 <= self.reads <= p.ordinary_count:
            raise ValueError("invalid public resource state")
        if abs(self.vote_sum) > self.reads or (self.reads - self.vote_sum) % 2:
            raise ValueError("vote_sum is inconsistent with the number of observations")
        if self.delayed_status not in ("pending", "corrupt", "observed"):
            raise ValueError("invalid delayed source status")
        if ((self.delayed_status == "observed" and self.delayed_vote not in (-1, 1)) or
                (self.delayed_status != "observed" and self.delayed_vote != 0)):
            raise ValueError("only observed sources may carry a public vote")

    @property
    def posterior(self):
        p = self.parameters
        odds = math.log(p.prior_probability / (1 - p.prior_probability))
        odds += self.vote_sum * math.log(p.ordinary_reliability / (1 - p.ordinary_reliability))
        if self.delayed_status == "observed":
            odds += self.delayed_vote * math.log(p.delayed_reliability / (1 - p.delayed_reliability))
        return 1 / (1 + math.exp(-odds)) if odds >= 0 else math.exp(odds) / (1 + math.exp(odds))

    @property
    def remaining_ticks(self):
        return self.parameters.horizon - self.tick

    @property
    def observed_source_ids(self):
        ids = tuple(f"ordinary/{i}" for i in range(self.reads))
        return ids + (("delayed/0",) if self.delayed_status == "observed" else ())

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        record = dict(data)
        record["parameters"] = TaskParameters(**record["parameters"])
        return cls(**record)

    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class StepResult:
    state: State
    reward: float
    cost: float
    done: bool
    info: dict

    @property
    def successor(self):
        return self.state

    def to_dict(self):
        return {"state": self.state.to_dict(), "reward": self.reward, "cost": self.cost,
                "done": self.done, "info": self.info}


def _uniform(seed, source_id):
    payload = f"round7/evidence/v1/{int(seed)}/{source_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") / 2**64


def generate_episode(seed, parameters=None, **overrides):
    p = parameters or TaskParameters()
    if isinstance(p, dict):
        p = TaskParameters(**p)
    if overrides:
        p = replace(p, **overrides)
    truth = 1 if _uniform(seed, "truth") < p.prior_probability else -1
    ordinary = tuple(truth if _uniform(seed, f"ordinary/{i}") < p.ordinary_reliability
                     else -truth for i in range(p.ordinary_count))
    delayed = truth if _uniform(seed, "delayed/0/vote") < p.delayed_reliability else -truth
    corrupt = _uniform(seed, "delayed/0/corrupt") < p.corruption_probability
    return Episode(int(seed), p, truth, ordinary, delayed, corrupt)


def initial_state(episode):
    return State(episode.parameters, remaining_budget=episode.parameters.budget)


def conditional_episode(state, seed, prefix_episode=None):
    """Sample H and unseen evidence conditional on public state, never on true H.

    Provide prefix_episode only to preserve the order of *already observed* source
    values in raw trace comparisons. Its truth and unseen votes are never used.
    Without it, a canonical ordering with the same sufficient statistic is used.
    """
    p = state.parameters
    namespace = "conditional/" + state.digest() + "/"
    truth = 1 if _uniform(seed, namespace + "truth") < state.posterior else -1
    if prefix_episode is not None:
        if prefix_episode.parameters != p:
            raise ValueError("prefix configuration mismatch")
        known = tuple(prefix_episode.ordinary_votes[:state.reads])
        if sum(known) != state.vote_sum:
            raise ValueError("observed ordinary evidence mismatch")
        if state.delayed_status == "observed" and prefix_episode.delayed_vote != state.delayed_vote:
            raise ValueError("observed delayed evidence mismatch")
    else:
        positive = (state.reads + state.vote_sum) // 2
        known = (1,) * positive + (-1,) * (state.reads - positive)
    unseen = tuple(truth if _uniform(seed, namespace + f"ordinary/{i}") < p.ordinary_reliability
                   else -truth for i in range(state.reads, p.ordinary_count))
    delayed = state.delayed_vote if state.delayed_status == "observed" else (
        truth if _uniform(seed, namespace + "delayed/0/vote") < p.delayed_reliability else -truth)
    if state.delayed_status == "pending":
        corrupt = _uniform(seed, namespace + "delayed/0/corrupt") < p.corruption_probability
    elif state.delayed_status == "corrupt":
        corrupt = True
    else:
        corrupt = prefix_episode.delayed_corrupt if prefix_episode is not None else False
    return Episode(int(seed), p, truth, known + unseen, delayed, corrupt)


def normalize_action(action):
    if isinstance(action, (int, np.integer)) and 0 <= int(action) < len(ACTIONS):
        return ACTIONS[int(action)]
    if isinstance(action, str) and action.upper() in ACTIONS:
        return action.upper()
    raise ValueError(f"unknown action: {action!r}")


def legal_actions(state):
    if state.terminated:
        return ()
    p = state.parameters
    if state.remaining_ticks <= 1:
        return ("STOP",)
    actions = []
    if state.reads < p.ordinary_count and state.remaining_budget >= p.read_budget:
        actions.append("READ")
    actions.append("WAIT")
    if state.delayed_status == "corrupt" and state.remaining_budget >= p.repair_budget:
        actions.append("REPAIR")
    return tuple(actions) + ("STOP",)


def features(state):
    """Identical public information for every arm, including costs/reliabilities."""
    p = state.parameters
    delay = max(0, p.arrival_tick - state.tick) if state.delayed_status == "pending" else 0
    return np.asarray((
        state.posterior, state.remaining_ticks / 8, state.remaining_budget / 8,
        (p.ordinary_count - state.reads) / 3, delay / 8,
        float(state.delayed_status == "pending"), float(state.delayed_status == "corrupt"),
        float(state.delayed_status == "observed"), p.ordinary_reliability,
        p.delayed_reliability, p.corruption_probability, p.read_budget / 8,
        p.repair_budget / 8, p.read_cost + p.latency_cost, p.wait_cost + p.latency_cost,
        p.repair_cost + p.latency_cost, p.stop_cost + p.latency_cost,
        p.invalid_attempt_cost,
    ), dtype=np.float64)


def step(state, action, episode):
    """One actual action; no random draws occur here, including during REPAIR."""
    if state.terminated:
        raise ValueError("cannot step a terminated state")
    if state.parameters != episode.parameters:
        raise ValueError("episode and state parameters differ")
    if sum(episode.ordinary_votes[:state.reads]) != state.vote_sum:
        raise ValueError("episode does not match this observed prefix")
    if state.delayed_status == "observed" and state.delayed_vote != episode.delayed_vote:
        raise ValueError("episode does not match the observed delayed source")
    if state.delayed_status == "corrupt" and not episode.delayed_corrupt:
        raise ValueError("episode does not match the observed corruption")
    requested = normalize_action(action)
    allowed = legal_actions(state)
    executed = requested if requested in allowed else "STOP"
    fallback = executed != requested
    p = state.parameters
    reason = None
    if fallback:
        if state.remaining_ticks <= 1:
            reason = "deadline_reserves_submission_tick"
        elif requested == "READ" and state.reads >= p.ordinary_count:
            reason = "no_unread_source"
        elif requested == "REPAIR" and state.delayed_status != "corrupt":
            reason = "no_corrupt_source"
        else:
            reason = "insufficient_budget"
    action_cost = getattr(p, executed.lower() + "_cost")
    invalid_cost = p.invalid_attempt_cost if fallback else 0.0
    cost = action_cost + p.latency_cost + invalid_cost
    debit = p.read_budget if executed == "READ" else p.repair_budget if executed == "REPAIR" else 0
    successor = replace(state, tick=state.tick + 1, terminated=(executed == "STOP"),
                        remaining_budget=state.remaining_budget - debit,
                        total_cost=state.total_cost + cost)
    observations = []
    events = []
    quality = 0.0
    if executed == "STOP":
        answer = 1 if state.posterior >= 0.5 else -1
        successor = replace(successor, terminated=True, answer=answer)
        quality = 1.0 if answer == episode.truth else -1.0
    else:
        if executed == "READ":
            vote = episode.ordinary_votes[state.reads]
            successor = replace(successor, reads=state.reads + 1, vote_sum=state.vote_sum + vote)
            observations.append({"source_id": f"ordinary/{state.reads}", "vote": vote,
                                 "reliability": p.ordinary_reliability, "via": "READ"})
        if executed == "REPAIR":
            successor = replace(successor, delayed_status="observed", delayed_vote=episode.delayed_vote)
            observations.append({"source_id": "delayed/0", "vote": episode.delayed_vote,
                                 "reliability": p.delayed_reliability, "via": "REPAIR"})
        if state.delayed_status == "pending" and state.tick < p.arrival_tick <= successor.tick:
            if episode.delayed_corrupt:
                successor = replace(successor, delayed_status="corrupt")
                events.append({"source_id": "delayed/0", "event": "arrived_corrupt"})
            else:
                successor = replace(successor, delayed_status="observed", delayed_vote=episode.delayed_vote)
                observations.append({"source_id": "delayed/0", "vote": episode.delayed_vote,
                                     "reliability": p.delayed_reliability, "via": "ARRIVAL"})
    info = {
        "requested_action": requested, "executed_action": executed,
        "guard_fallback": fallback, "guard_reason": reason,
        "legal_actions": list(allowed), "prefix_digest": state.digest(),
        "posterior_before": state.posterior, "posterior_after": successor.posterior,
        "new_observations": observations, "events": events,
        "costs": {"action": action_cost, "latency": p.latency_cost, "invalid_attempt": invalid_cost,
                  "total": cost, "budget_debit": debit, "ticks": 1},
        "terminal_quality": quality if successor.terminated else None,
    }
    return StepResult(successor, quality - cost, cost, successor.terminated, info)
