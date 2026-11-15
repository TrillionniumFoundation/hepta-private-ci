"""Bounded, causal action receipts for PRED; references are not authentication.

The host must supply authentic identities, clocks, costs and readbacks. This
adapter validates their structure; it does not establish real execution or
connect a production owner. Effect durations retain Evidence's existing units.
Unknown numeric slots have a separate known bit and are never zero labels.
"""

from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real
import math

import numpy as np

from .contracts import (
    Evidence,
    EvidenceSource,
    EffectTimeKind,
    ObservationStatus,
    allowed_mask,
)


class Stage(str, Enum):
    REQUEST = "request"
    ACCEPTED = "accepted"
    EXECUTED = "executed"
    EFFECT_OBSERVED = "effect_observed"
    READBACK = "readback"


TIME_VALUES = (
    "observed_elapsed",
    "arrival_gap",
    "event_delay",
    "request_age",
    "execution_age",
    "deadline_remaining",
    "effect_lower",
    "effect_upper",
)
OTHER_VALUES = ("remaining_budget", "confirmed_cost", "final_cost", "outcome")
MAX_EVENTS = 255
MAX_ACTIONS = 64


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be finite nonnegative numeric data")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite nonnegative numeric data")
    return value


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(
            "identities must be nonempty strings of at most 256 characters"
        )
    return value


@dataclass(frozen=True)
class ActionEvent:
    """One arrival, linked to a request; event_at is the phase occurrence time."""

    sequence: int
    action_id: str
    candidate_id: str
    action: str
    stage: Stage
    observed_at: float
    record_ref: str
    event_at: float | None = None
    remaining_budget: float | None = None
    deadline_at: float | None = None
    evidence: Evidence | None = None
    source: EvidenceSource = EvidenceSource.REAL

    def __post_init__(self):
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, Integral)
            or self.sequence < 0
        ):
            raise ValueError("sequence must be a nonnegative integer")
        for name in ("action_id", "candidate_id", "action", "record_ref"):
            _identifier(getattr(self, name))
        object.__setattr__(self, "stage", Stage(self.stage))
        object.__setattr__(self, "source", EvidenceSource(self.source))
        if self.source == EvidenceSource.IMAGINED:
            raise ValueError("imagined rollouts cannot enter factual history")
        for name in ("observed_at", "event_at", "remaining_budget", "deadline_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, name))
        if self.observed_at is None or (
            self.event_at is not None and self.event_at > self.observed_at
        ):
            raise ValueError("phase occurrence cannot follow receipt arrival")
        if self.stage == Stage.REQUEST and self.event_at is None:
            raise ValueError("request requires its occurrence time")
        receipt_stage = self.stage in (Stage.READBACK, Stage.EFFECT_OBSERVED)
        if (receipt_stage and not isinstance(self.evidence, Evidence)) or (
            not receipt_stage and self.evidence is not None
        ):
            raise ValueError("only readback/effect stages require Evidence")
        if self.evidence is not None:
            if (
                self.evidence.source != self.source
                or self.evidence.observed_at != self.observed_at
            ):
                raise ValueError("evidence source and arrival must match its envelope")
            terminal = self.evidence.observation_status == ObservationStatus.TERMINAL
            if terminal != (self.stage == Stage.EFFECT_OBSERVED):
                raise ValueError("terminal readback belongs to effect_observed")


@dataclass(frozen=True)
class EncodedHistory:
    """An immutable numerical snapshot, including a final decision-context row."""

    features: np.ndarray
    feature_names: tuple[str, ...]
    events: tuple[ActionEvent, ...]
    through_sequence: int
    decision_at: float


def _check_receipts(receipts, execution_at):
    """Intersect factual time/cost constraints in continuous units.

    This is independent of the finite training grid: an off-grid real duration
    can be valid history while requiring another label-support model. A later
    ACK must also agree with every fact that arrived before it.
    """
    lower_bounds, upper_bounds = [(0.0, False)], []
    confirmed_cost, final_cost = 0.0, None
    for receipt in receipts:
        evidence = receipt.evidence
        confirmed_cost = max(confirmed_cost, evidence.confirmed_cost_lower_bound)
        if evidence.final_cost is not None:
            if final_cost is not None and final_cost != evidence.final_cost:
                raise ValueError("conflicting final cost evidence")
            final_cost = evidence.final_cost
        if evidence.time_kind == EffectTimeKind.EXACT:
            lower_bounds.append((evidence.time_lower, False))
            upper_bounds.append(evidence.time_upper)
        elif evidence.time_kind == EffectTimeKind.INTERVAL:
            lower_bounds.append((evidence.time_lower, True))
            upper_bounds.append(evidence.time_upper)
        elif evidence.time_kind == EffectTimeKind.RIGHT_CENSORED:
            lower_bounds.append((evidence.time_lower, True))
        if execution_at is not None:
            if (
                evidence.time_lower is not None
                and execution_at + evidence.time_lower > receipt.observed_at
            ):
                raise ValueError("effect duration extends beyond its observed receipt")
            if evidence.observation_status == ObservationStatus.TERMINAL:
                upper_bounds.append(receipt.observed_at - execution_at)
                if receipt.event_at is not None:
                    elapsed = receipt.event_at - execution_at
                    lower_bounds.append((elapsed, False))
                    upper_bounds.append(elapsed)
    lower = max(value for value, _ in lower_bounds)
    upper = min(upper_bounds, default=math.inf)
    lower_open = any(
        value == lower and open_bound for value, open_bound in lower_bounds
    )
    if lower > upper or (lower == upper and lower_open):
        raise ValueError("conflicting effect duration or occurrence evidence")
    if final_cost is not None and final_cost < confirmed_cost:
        raise ValueError("final cost is below a previously confirmed cost bound")


def encode(
    events, *, actions, decision_at, through_sequence, remaining_budget, deadline_at
):
    """Encode only the observed prefix at an explicit arrival cursor.

    Tied arrival timestamps are resolved by through_sequence, so a later event
    at the same clock tick cannot alter an already frozen decision. Missing
    acceptance/execution ACKs stay missing even when a later phase is visible.
    Features are in [0, 1], using v/(1+v); masks preserve known zero values.
    """
    actions = tuple(actions)
    if not 1 <= len(actions) <= MAX_ACTIONS or len(set(actions)) != len(actions):
        raise ValueError("need 1..64 unique registered actions")
    for name in actions:
        _identifier(name)
    decision_at = _number(decision_at, "decision_at")
    remaining_budget = _number(remaining_budget, "remaining_budget")
    deadline_at = _number(deadline_at, "deadline_at")
    if (
        isinstance(through_sequence, bool)
        or not isinstance(through_sequence, Integral)
        or through_sequence < -1
    ):
        raise ValueError("through_sequence must be an integer >= -1")
    # Bound consumption even when a caller supplies an iterator.
    visible = []
    for i, event in enumerate(events):
        if i >= MAX_EVENTS:
            raise ValueError("history exceeds 255 arrivals")
        if not isinstance(event, ActionEvent):
            raise ValueError("expected ActionEvent")
        if event.sequence <= through_sequence and event.observed_at <= decision_at:
            visible.append(event)
    names = tuple("action:" + a for a in actions) + ("action_slot",)
    names += tuple("stage:" + s.value for s in Stage) + ("stage:decision",)
    names += tuple("source:" + s for s in ("real", "simulator"))
    names += tuple("status:" + s.value for s in ObservationStatus)
    names += tuple(
        "time_kind:" + s for s in ("exact", "interval", "right_censored", "unobserved")
    )
    names += tuple(
        n + suffix for n in TIME_VALUES + OTHER_VALUES for suffix in ("", "_known")
    )
    index = {name: i for i, name in enumerate(names)}
    rows, identities, phases, receipts = [], {}, {}, {}
    previous_sequence, previous_arrival = -1, 0.0
    for event in visible:
        if event.sequence <= previous_sequence or event.observed_at < previous_arrival:
            raise ValueError(
                "history must preserve strictly increasing sequence and arrival order"
            )
        previous_sequence = event.sequence
        if event.action not in actions:
            raise ValueError("unregistered action")
        identity = (event.candidate_id, event.action, event.source)
        if event.action_id not in identities:
            if event.stage != Stage.REQUEST or len(identities) >= MAX_ACTIONS:
                raise ValueError(
                    "each action needs an observed request; at most 64 identities"
                )
            identities[event.action_id] = identity
            phases[event.action_id] = {}
            receipts[event.action_id] = []
        if identities[event.action_id] != identity:
            raise ValueError("action identity changed candidate, action or source")
        known = phases[event.action_id]
        if event.stage != Stage.READBACK:
            if event.stage in known:
                raise ValueError("duplicate lifecycle phase")
            known[event.stage] = event.event_at
        elif Stage.EFFECT_OBSERVED in known:
            raise ValueError("nonterminal readback cannot undo terminal evidence")
        times = [known[s] for s in list(Stage)[:4] if known.get(s) is not None]
        if times != sorted(times):
            raise ValueError("lifecycle occurrence times are inconsistent")
        if event.evidence is not None:
            receipts[event.action_id].append(event)
        _check_receipts(receipts[event.action_id], known.get(Stage.EXECUTED))
        values = dict.fromkeys(TIME_VALUES + OTHER_VALUES)
        values.update(
            observed_elapsed=event.observed_at,
            arrival_gap=event.observed_at - previous_arrival,
        )
        previous_arrival = event.observed_at
        values["event_delay"] = (
            None if event.event_at is None else event.observed_at - event.event_at
        )
        for name, stage in (
            ("request_age", Stage.REQUEST),
            ("execution_age", Stage.EXECUTED),
        ):
            values[name] = (
                None if known.get(stage) is None else event.observed_at - known[stage]
            )
        values["remaining_budget"] = event.remaining_budget
        values["deadline_remaining"] = (
            None
            if event.deadline_at is None
            else max(0, event.deadline_at - event.observed_at)
        )
        row = np.zeros(len(names))
        row[index["action:" + event.action]] = 1
        row[index["action_slot"]] = (
            list(identities).index(event.action_id) + 1
        ) / MAX_ACTIONS
        row[index["stage:" + event.stage.value]] = 1
        row[index["source:" + event.source.value]] = 1
        if event.evidence is not None:
            evidence = event.evidence
            row[index["status:" + evidence.observation_status.value]] = 1
            row[index["time_kind:" + evidence.time_kind.value]] = 1
            values.update(
                effect_lower=evidence.time_lower,
                effect_upper=evidence.time_upper,
                confirmed_cost=evidence.confirmed_cost_lower_bound,
                final_cost=evidence.final_cost,
                outcome=evidence.outcome,
            )
        for name, value in values.items():
            if value is not None:
                row[index[name]], row[index[name + "_known"]] = value / (1 + value), 1
        rows.append(row)
    row = np.zeros(len(names))
    row[index["stage:decision"]] = 1
    for name, value in (
        ("observed_elapsed", decision_at),
        ("arrival_gap", decision_at - previous_arrival),
        ("remaining_budget", remaining_budget),
        ("deadline_remaining", max(0, deadline_at - decision_at)),
    ):
        row[index[name]], row[index[name + "_known"]] = value / (1 + value), 1
    rows.append(row)
    features = np.asarray(rows, dtype=np.float64)
    # Immutable backing bytes prevent resetting WRITEABLE on the returned array.
    frozen = np.frombuffer(features.tobytes(), dtype=np.float64).reshape(features.shape)
    return EncodedHistory(
        frozen, names, tuple(visible), int(through_sequence), decision_at
    )


def ablate(snapshot, mode):
    """Return model inputs for a prespecified information ablation.

    no_history retains the newest event and current decision context, removing
    request/execution ages derived from older events. It does not reset a model
    state: Model.forward(reset=True) uses only its final row, a different test.
    no_time removes all timing values, availability bits and time-kind fields;
    sequence order and receipt status remain observable.
    """
    if mode not in ("full", "no_action", "no_time", "no_history"):
        raise ValueError("unknown history ablation")
    x = snapshot.features.copy()
    if mode == "no_history":
        x = x[-2:]
    for i, name in enumerate(snapshot.feature_names):
        action = name.startswith("action:") or name == "action_slot"
        time = (
            name.startswith("time_kind:") or name.removesuffix("_known") in TIME_VALUES
        )
        age = name.removesuffix("_known") in ("request_age", "execution_age")
        if (
            mode == "no_action"
            and action
            or mode == "no_time"
            and time
            or mode == "no_history"
            and age
        ):
            x[:, i] = 0
        if mode == "no_history" and name == "action_slot":
            x[:, i] = 0
        if (
            mode == "no_history"
            and len(x) == 2
            and name in ("arrival_gap", "arrival_gap_known")
        ):
            x[0, i] = 0
    return x


def supervision(event):
    """Existing finite joint mask; unsupported effect/cost support is rejected.

    Missing readbacks provide no outcome/time label. Right censoring is admitted
    only by Evidence's verified-ongoing witness rule. The host must separately
    join subsequent labels to an earlier frozen input without backfilling it.
    """
    if not isinstance(event, ActionEvent) or event.evidence is None:
        raise ValueError("supervision requires a factual readback")
    return allowed_mask(event.evidence)
