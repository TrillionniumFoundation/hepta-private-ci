"""Narrow typed reuse of terminal, absorbing-cycle and regenerative operators.

No conversion from a terminal marginal to a path law is defined. The terminal
law already describes the requested endpoint; this module does not propagate it.
"""

from dataclasses import dataclass
from enum import Enum
import math

import numpy as np

from ..round4 import runtime_codec, runtime_law
from .vendor.first_passage_cell.cell import CellParameters, FirstPassageCell
from .vendor.first_passage_cell.filtering import EventObservation, survival_filter
from .vendor.first_passage_cell.kernels import first_passage


class BoundarySide(str, Enum):
    LOWER = "lower"
    UPPER = "upper"


@dataclass(frozen=True)
class TerminalForecast:
    """An explicit conditional endpoint law, with its declared time window."""

    law: dict
    condition_time: float
    horizon: float
    lower: float
    upper: float


@dataclass(frozen=True)
class BrownianPath:
    """Known physical initial state and constant coefficients until first hit."""

    initial_level: float
    drift: float
    sigma: float
    barrier: float
    side: BoundarySide


@dataclass(frozen=True)
class FirstPassageForecast:
    path: BrownianPath
    condition_time: float
    horizon: float
    discount: float = 0.0


@dataclass(frozen=True)
class CycleObservation:
    """One lower-barrier absorbing cycle; grid values are positive distances."""

    grid: tuple
    live_mass: tuple
    prior_event_mass: float
    drift: float
    sigma: float
    condition_time: float
    horizon: float
    observation: EventObservation
    sensor: tuple | None = None
    tail_mass_limit: float = 1.0


def _window(condition_time, horizon):
    values = (condition_time, horizon)
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Finite nonnegative physical time and horizon required")
    end = condition_time + horizon
    if not math.isfinite(end):
        raise ValueError("Unrepresentable physical end time")
    return {"condition_time": float(condition_time), "horizon": float(horizon), "time": float(end)}


def forecast(request):
    """Dispatch only explicitly typed requests; return physical FP64 values."""
    if isinstance(request, TerminalForecast):
        clock = _window(request.condition_time, request.horizon)
        logs = runtime_law.event_logs(request.law, request.lower, request.upper)
        return {"schema": "hepta.analytic-interop.forecast.v1", "semantics": "terminal_state",
                **clock, "channels": ["put", "neutral", "call"],
                "lower": request.lower, "upper": request.upper,
                "physical_probabilities": np.exp(logs).tolist(), "log_probabilities": logs.tolist()}
    if not isinstance(request, FirstPassageForecast) or not isinstance(request.path, BrownianPath):
        raise TypeError("Explicit terminal request or Brownian path model required; no marginal conversion")
    clock = _window(request.condition_time, request.horizon)
    path = request.path
    if not isinstance(path.side, BoundarySide):
        raise TypeError("Explicit lower/upper BoundarySide required")
    if not all(math.isfinite(v) for v in (path.initial_level, path.drift, path.sigma, path.barrier)):
        raise ValueError("Finite physical path coefficients required")
    orientation = 1 if path.side is BoundarySide.LOWER else -1
    distance = orientation * (path.initial_level - path.barrier)
    if distance < 0:
        raise ValueError("Initial state must lie in the live half-line or exactly on its boundary")
    values = first_passage(distance, orientation * path.drift, path.sigma,
                           request.horizon, request.discount)
    return {"schema": "hepta.analytic-interop.forecast.v1", "semantics": "first_passage_cycle",
            **clock, "boundary_side": path.side.value, "reset": "none",
            "hit_probability": float(values["F"]), "survival_probability": float(values["S"]),
            "hit_density_per_time": float(values["f"]), "discounted_hit_weight": float(values["H"]),
            "discount_per_time": request.discount,
            "log_values": {k: float(values[k]) for k in ("log_F", "log_S", "log_f", "log_H")}}


def observe_cycle(request):
    """Condition a projected absorbing belief only on the declared observation."""
    if not isinstance(request, CycleObservation) or not isinstance(request.observation, EventObservation):
        raise TypeError("Explicit absorbing-cycle request and event observation required")
    clock = _window(request.condition_time, request.horizon)
    result = survival_filter(request.grid, request.live_mass, request.drift, request.sigma,
                             request.horizon, event_observation=request.observation,
                             prior_event_mass=request.prior_event_mass, sensor=request.sensor,
                             tail_mass_limit=request.tail_mass_limit)
    result["alive_mass"] = result["alive_mass"].tolist()
    return {"schema": "hepta.analytic-interop.belief.v1", "semantics": "absorbing_cycle_belief",
            **clock, **result}


def new_regenerative_cell(parameters, *, initial_level, seed):
    """Return the original physical state owner, including reset and RNG state."""
    if not isinstance(parameters, CellParameters):
        raise TypeError("Selected CellParameters and a real initial level are required")
    return FirstPassageCell(parameters, initial_level, seed)


def restore_regenerative_cell(checkpoint, *, expected_model_digest):
    """Restore only the original model-bound physical checkpoint schema."""
    return FirstPassageCell.from_checkpoint(checkpoint, expected_model_digest)


def decode_communication(decoder, packet):
    """Apply actual signed Round4 bytes; packet silence is not survival evidence."""
    if not isinstance(decoder, runtime_codec.Decoder) or decoder.mode != "event":
        raise TypeError("Original Round4 signed-event decoder required")
    previous = None if decoder.values is None else list(decoder.values)
    law = decoder.apply(packet)
    kind = runtime_codec.KINDS[runtime_codec.HEADER.unpack(packet[:runtime_codec.HEADER.size])[3]]
    zero_delta = decoder.values == (previous if previous is not None else [0] * len(decoder.values))
    return {"schema": "hepta.analytic-interop.communication.v1",
            "semantics": "signed_terminal_law_communication", "packet_kind": kind,
            "zero_delta": zero_delta, "sequence": decoder.sequence, "time": decoder.time, "law": law}
