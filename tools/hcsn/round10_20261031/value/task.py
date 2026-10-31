"""Finite, causal evidence task shared with the preread native owner.

Policy inputs contain only public state. World.truth/votes/failures are private
and are only consumed by execute after the guard has selected an actual READ.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math

import numpy as np

ACTIONS = ("READ", "WAIT", "STOP")


@dataclass(frozen=True)
class Packet:
    arrival: int
    reliability: float
    failure_probability: float = 0.0


@dataclass(frozen=True)
class Config:
    deadline: int
    budget: int
    prior: float
    read_cost: float
    latency_cost: float
    stop_cost: float
    failure_cost: float
    invalid_cost: float
    refractory_ticks: int
    packets: tuple

    def __post_init__(self):
        if not 0 < self.prior < 1 or not 0 <= self.budget <= 8:
            raise ValueError("invalid prior/budget")
        if not 1 <= self.deadline <= 16 or not 0 <= self.refractory_ticks <= 8:
            raise ValueError("invalid deadline/refractory period")
        if not 1 <= len(self.packets) <= 4:
            raise ValueError("this experiment supports one to four packets")
        if tuple(p.arrival for p in self.packets) != tuple(sorted(p.arrival for p in self.packets)):
            raise ValueError("packets must be sorted before execution")
        for p in self.packets:
            if p.arrival < 0 or not .5 < p.reliability < 1 or not 0 <= p.failure_probability < 1:
                raise ValueError("invalid public packet model")
        if any(not math.isfinite(x) or x < 0 for x in self.costs):
            raise ValueError("costs must be finite and nonnegative")

    @property
    def costs(self):
        return (self.read_cost, self.latency_cost, self.stop_cost,
                self.failure_cost, self.invalid_cost)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class State:
    clock: int = 0
    budget_left: int = 0
    recovery_until: int = 0
    next_packet: int = 0
    history: str = ""
    paid_cost: float = 0.0
    terminated: bool = False
    answer: int | None = None

    @property
    def key(self):
        return (f"t={self.clock};b={self.budget_left};r={self.recovery_until};"
                f"i={self.next_packet};h={self.history}")


@dataclass(frozen=True)
class World:
    truth: int
    votes: tuple
    failures: tuple


def initial(config):
    return State(budget_left=config.budget)


def validate(config, state):
    if not 0 <= state.clock <= config.deadline or not 0 <= state.budget_left <= config.budget:
        raise ValueError("invalid public resources")
    if not 0 <= state.next_packet <= len(config.packets) or len(state.history) != state.next_packet:
        raise ValueError("invalid history length")
    if any(bit not in "01x" for bit in state.history) or state.paid_cost < 0:
        raise ValueError("invalid evidence/ledger")


def posterior(config, state):
    odds = math.log(config.prior / (1 - config.prior))
    for bit, p in zip(state.history, config.packets):
        if bit != "x":
            odds += (1 if bit == "1" else -1) * math.log(p.reliability / (1 - p.reliability))
    return 1 / (1 + math.exp(-odds))


def legal(config, state):
    if state.terminated:
        return ()
    result = ["STOP"]
    if state.clock < config.deadline:
        result.append("WAIT")
        if (state.budget_left > 0 and state.next_packet < len(config.packets)
                and state.clock >= state.recovery_until
                and config.packets[state.next_packet].arrival <= state.clock):
            result.append("READ")
    return tuple(result)


def successor(config, state, action, observation=None):
    """Deterministic public transition. READ observation is supplied after I/O."""
    validate(config, state)
    if state.terminated:
        raise ValueError("terminal task")
    if action not in ACTIONS:
        raise ValueError("unknown action")
    actual = action if action in legal(config, state) else "STOP"
    invalid = action != actual
    if actual == "STOP":
        cost = config.stop_cost + (config.invalid_cost if invalid else 0)
        out = replace(state, terminated=True, answer=int(posterior(config, state) >= .5),
                      paid_cost=state.paid_cost + cost)
    elif actual == "WAIT":
        cost = config.latency_cost
        out = replace(state, clock=state.clock + 1, paid_cost=state.paid_cost + cost)
    else:
        if observation not in ("0", "1", "x"):
            raise ValueError("READ requires the actually decoded observation or failure")
        cost = config.read_cost + (config.failure_cost if observation == "x" else 0)
        out = replace(state, clock=state.clock + 1, budget_left=state.budget_left - 1,
                      recovery_until=state.clock + 1 + config.refractory_ticks,
                      next_packet=state.next_packet + 1, history=state.history + observation,
                      paid_cost=state.paid_cost + cost)
    return out, cost, actual


def execute(config, state, world, requested):
    """No private packet access occurs unless the public guard allows READ."""
    observation = None
    read = requested == "READ" and requested in legal(config, state)
    if read:
        index = state.next_packet
        observation = "x" if world.failures[index] else str(world.votes[index])
    nxt, cost, actual = successor(config, state, requested, observation)
    return nxt, {"requested": requested, "actual": actual, "read_attempted": read,
                 "observation": observation, "cost": cost, "before": state.key,
                 "after": nxt.key, "answer": nxt.answer}


def generate_world(config, seed):
    rng = np.random.default_rng(seed)
    truth = int(rng.random() < config.prior)
    votes = tuple(truth if rng.random() < p.reliability else 1 - truth for p in config.packets)
    failures = tuple(bool(rng.random() < p.failure_probability) for p in config.packets)
    return World(truth, votes, failures)


def rollout(config, world, policy, start=None, forced_first=None):
    state = initial(config) if start is None else start
    prefix_cost = state.paid_cost
    trace = []
    for decision in range(config.deadline + 2):
        action = forced_first if decision == 0 and forced_first is not None else policy(config, state)
        state, row = execute(config, state, world, action)
        trace.append(row)
        if state.terminated:
            quality = int(state.answer == world.truth)
            return {"quality": quality, "utility": quality - (state.paid_cost - prefix_cost),
                    "cost": state.paid_cost - prefix_cost, "clock": state.clock,
                    "reads": state.next_packet, "state": asdict(state), "trace": trace}
    raise RuntimeError("task exceeded its finite horizon")


def config_digest(config):
    return hashlib.sha256(json.dumps(config.to_dict(), sort_keys=True).encode()).hexdigest()
