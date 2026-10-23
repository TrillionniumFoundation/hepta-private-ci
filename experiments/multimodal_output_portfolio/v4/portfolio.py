"""Research-only finite, state-feedback allocation of four output modalities.

This is a deterministic, auditable *mechanism* reference, not a trained decoder,
foundation model, FBSDE solver, scientific superiority claim or action grant.
There are no hidden truth labels or future innovations in policy inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import math
import random
from typing import NamedTuple

MODALITIES = ("text", "audio", "image", "video")
MAX_LEVEL = 2
# A shared event changes *all* active modalities. Independent marginals would
# destroy precisely the cross-modality risk this finite pilot needs to test.
SHOCK_PROBS = (0.20, 0.25, 0.55)  # failure, one-step gain, full gain


@dataclass(frozen=True)
class Config:
    horizon: int = 2
    max_units_per_step: int = 2
    unit_cost: int = 1
    activation_cost: int = 1
    emission_cost_each: int = 1
    risk_aversion: float = 0.5
    cost_shadow_price: float = 0.1
    sync_penalty: int = 5

    def __post_init__(self) -> None:
        if (self.horizon < 1 or self.horizon > 3
            or not 1 <= self.max_units_per_step <= 4
            or self.unit_cost <= 0 or self.activation_cost < 0
            or self.emission_cost_each <= 0
            or not math.isfinite(self.risk_aversion)
            or self.risk_aversion < 0 or self.risk_aversion > 10
            or not math.isfinite(self.cost_shadow_price)
            or self.cost_shadow_price < 0 or self.sync_penalty < 0):
            raise ValueError("unadmitted control profile")

    @property
    def emission_reserve(self) -> int:
        return len(MODALITIES) * self.emission_cost_each


@dataclass(frozen=True)
class State:
    # Public, observable generation proxy levels. Not factual truth labels.
    levels: tuple[int, int, int, int]
    remaining: int
    step: int = 0
    active_mask: int = 0

    def __post_init__(self) -> None:
        if (len(self.levels) != 4
            or any(type(x) is not int or not 0 <= x <= MAX_LEVEL for x in self.levels)
            or type(self.remaining) is not int or self.remaining < 0
            or type(self.step) is not int or self.step < 0
            or type(self.active_mask) is not int or not 0 <= self.active_mask < 16):
            raise ValueError("invalid public portfolio state")


@dataclass(frozen=True)
class Allocation:
    # No fourth-modality weight may be silently dropped from final emission.
    units: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        if (len(self.units) != 4
            or any(type(x) is not int or x < 0 or x > 2 for x in self.units)):
            raise ValueError("invalid four-channel allocation")

    @property
    def stop(self) -> bool:
        return not any(self.units)

    @property
    def mask(self) -> int:
        return sum((1 << i) for i, u in enumerate(self.units) if u)


STOP = Allocation((0, 0, 0, 0))


class Decoded(NamedTuple):
    text: str
    audio: tuple[int, ...]
    image: tuple[tuple[int, ...], ...]
    video: tuple[tuple[tuple[int, ...], ...], ...]


def decode_all(state: State) -> Decoded:
    """Four *actually materialized* distinct toy outputs from current levels."""
    t, a, i, v = state.levels
    return Decoded(f"symbol:{t}", (a, -a, a, -a),
                   ((i, i), (i, i)),
                   (((v, v), (v, v)), ((v, v), (v, v))))


def decoded_external_loss(output: Decoded, sync_penalty: int) -> int:
    """Independent raw-output scorer for the known-target *synthetic* task.

    This scorer is an offline fixture, not a real observer, human preference, or
    a live model's permission to consult hidden reference labels.
    """
    if (len(output.audio) != 4 or len(output.image) != 2
        or len(output.video) != 2 or not output.text.startswith("symbol:")):
        raise ValueError("incomplete output")
    t = int(output.text.removeprefix("symbol:"))
    a = output.audio[0]
    i = output.image[0][0]
    v = output.video[0][0][0]
    if (output.audio != (a, -a, a, -a)
        or output.image != ((i, i), (i, i))
        or output.video != (((v, v), (v, v)), ((v, v), (v, v)))
        or any(q not in (0, 1, 2) for q in (t, a, i, v))):
        raise ValueError("inconsistent or malformed output")
    return (sum((MAX_LEVEL - q) ** 2 for q in (t, a, i, v))
            + sync_penalty * (i != v)
            + sync_penalty * (abs(t - a) > 1))


def charge(state: State, action: Allocation, cfg: Config) -> int:
    activations = (action.mask & ~state.active_mask).bit_count()
    return sum(action.units) * cfg.unit_cost + activations * cfg.activation_cost


def feasible(state: State, action: Allocation, cfg: Config) -> bool:
    if state.remaining < cfg.emission_reserve:
        return False
    if action.stop:
        return True
    return (state.step < cfg.horizon
            and sum(action.units) <= cfg.max_units_per_step
            and charge(state, action, cfg) + cfg.emission_reserve <= state.remaining)


def actions(state: State, cfg: Config) -> tuple[Allocation, ...]:
    if state.remaining < cfg.emission_reserve:
        raise ValueError("cannot pay for mandatory four-modality emission")
    out = [STOP]
    if state.step < cfg.horizon:
        for t in range(3):
            for a in range(3):
                for i in range(3):
                    for v in range(3):
                        candidate = Allocation((t, a, i, v))
                        if not candidate.stop and feasible(state, candidate, cfg):
                            out.append(candidate)
    return tuple(out)


def advance(state: State, action: Allocation, shock: int, cfg: Config) -> State:
    if action.stop or not feasible(state, action, cfg):
        raise ValueError("unsupported generation action")
    if type(shock) is not int or shock not in (0, 1, 2):
        raise ValueError("unregistered innovation")
    levels = tuple(min(MAX_LEVEL, q + min(u, shock))
                   for q, u in zip(state.levels, action.units))
    return State(levels, state.remaining - charge(state, action, cfg),
                 state.step + 1, action.mask)


def conditional_ce(values: tuple[float, ...],
                   probabilities: tuple[float, ...], risk_aversion: float) -> float:
    if (not values or len(values) != len(probabilities)
        or any(not math.isfinite(x) for x in values)
        or any(not math.isfinite(p) or p < 0 for p in probabilities)
        or not math.isclose(sum(probabilities), 1.0, abs_tol=1e-12)
        or not math.isfinite(risk_aversion) or risk_aversion < 0):
        raise ValueError("invalid conditional risk law")
    if risk_aversion == 0:
        return sum(p * v for p, v in zip(probabilities, values))
    anchor = min(values)
    scaled = sum(p * math.exp(-risk_aversion * (v - anchor))
                 for p, v in zip(probabilities, values))
    if scaled <= 0:
        raise ValueError("unsupported numerical risk profile")
    return anchor - math.log(scaled) / risk_aversion


class Controller:
    """Finite exact-support Bellman solver; no neural optimality is implied."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _terminal(self, state: State) -> float:
        return (-decoded_external_loss(decode_all(state), self.cfg.sync_penalty)
                -self.cfg.cost_shadow_price * self.cfg.emission_reserve)

    @lru_cache(maxsize=65536)
    def solve(self, state: State) -> tuple[Allocation, float]:
        if state.step > self.cfg.horizon:
            raise ValueError("generation horizon exceeded")
        available = actions(state, self.cfg)
        best, best_value = STOP, self._terminal(state)
        for action in available[1:]:
            next_values = tuple(self.solve(advance(state, action, k, self.cfg))[1]
                                for k in range(len(SHOCK_PROBS)))
            value = (-self.cfg.cost_shadow_price * charge(state, action, self.cfg)
                     + conditional_ce(next_values, SHOCK_PROBS, self.cfg.risk_aversion))
            if value > best_value + 1e-12:
                best, best_value = action, value
        return best, best_value


def covariance_for_action(state: State, action: Allocation,
                          cfg: Config) -> tuple[tuple[float, ...], ...]:
    """Joint conditional covariance of four *observed* level improvements."""
    if action.stop or not feasible(state, action, cfg):
        raise ValueError("not a feasible active allocation")
    outcomes = [tuple(n - old for n, old in zip(advance(state, action, k, cfg).levels,
                                                state.levels)) for k in range(3)]
    mean = [sum(p * o[j] for p, o in zip(SHOCK_PROBS, outcomes)) for j in range(4)]
    return tuple(tuple(sum(p * (o[i] - mean[i]) * (o[j] - mean[j])
                           for p, o in zip(SHOCK_PROBS, outcomes))
                       for j in range(4)) for i in range(4))


def execute(initial: State, cfg: Config, seed: int) -> dict:
    """Run a causal observed-feedback trajectory; no test truth is an input."""
    rng = random.Random(seed)
    policy = Controller(cfg)
    state = initial
    records: list[dict] = []
    while True:
        action, value = policy.solve(state)
        if not feasible(state, action, cfg):
            raise AssertionError("policy returned infeasible action")
        record = {"step": state.step, "before_levels": state.levels,
                  "before_budget": state.remaining, "allocation": action.units,
                  "estimated_value": value, "control_cost": 0 if action.stop
                  else charge(state, action, cfg)}
        if action.stop:
            records.append(record)
            break
        draw = rng.random()  # Sample AFTER action: no future-noise access.
        shock = 0 if draw < SHOCK_PROBS[0] else (1 if draw < sum(SHOCK_PROBS[:2]) else 2)
        state = advance(state, action, shock, cfg)
        record["observed_shock"] = shock
        record["after_levels"] = state.levels
        record["after_budget"] = state.remaining
        records.append(record)
    emission = decode_all(state)
    if state.remaining < cfg.emission_reserve:
        raise AssertionError("unfunded emission")
    raw = {"text": emission.text, "audio": emission.audio,
           "image": emission.image, "video": emission.video}
    bytes_out = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    spent = initial.remaining - state.remaining + cfg.emission_reserve
    trace = {"schema": "hepta.ndu.modality-portfolio.trace.v1",
             "initial": asdict(initial), "config": asdict(cfg),
             "records": records, "terminal_levels": state.levels,
             "output_sha256": hashlib.sha256(bytes_out).hexdigest()}
    trace_hash = hashlib.sha256(json.dumps(
        trace, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return {"scope": "RESEARCH_ONLY_DENY_ALL", "records": records,
            "trace_sha256": trace_hash,
            "outputs": raw, "output_sha256": hashlib.sha256(bytes_out).hexdigest(),
            "remaining_after_emission": state.remaining - cfg.emission_reserve,
            "spent": spent, "external_fixture_loss": decoded_external_loss(emission, cfg.sync_penalty)}
