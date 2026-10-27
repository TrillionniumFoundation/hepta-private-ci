"""Joint observation law, preserving unknown couplings and arrival information.

The 110 events implement the audited allocator's alias-iff-equal protocol.
That protocol is not a universal property of speech. Distinct recordings may
remain dependent; this module never manufactures their law from marginals.
"""

from dataclasses import dataclass
import math

import numpy as np

from ...advance_20261026.control.followup.unique_evidence import (
    EvidenceFilter, JointEvidenceModel, Outcome, Receipt,
)


SCHEMA = "hepta.repair.joint-observation.v1"
PROTOCOL = "audited_allocator_alias_iff_equal_targets"
OUTCOMES = tuple(Outcome((0, 0), (o, o)) for o in range(10)) + tuple(
    Outcome((0, 1), (left, right)) for left in range(10) for right in range(10))
DIAGONAL = np.arange(10) * 11


def probability(value, size=100):
    p = np.asarray(value, dtype=np.float64)
    if (p.shape != (size,) or not np.isfinite(p).all() or (p < 0).any()
            or not math.isclose(float(p.sum()), 1., rel_tol=0., abs_tol=1e-10)):
        raise ValueError("A finite normalized joint probability vector is required")
    return p.copy()


@dataclass(frozen=True)
class PairObservation:
    """Previously measured paired outcomes; hidden targets are fitting-only data."""

    sample_id: str
    source_group: str
    target: int
    event_ids: tuple
    values: tuple

    def outcome_index(self):
        if (type(self.sample_id) is not str or not self.sample_id
                or type(self.source_group) is not str or not self.source_group or type(self.target) is not int
                or not 0 <= self.target < 100 or type(self.event_ids) is not tuple or len(self.event_ids) != 2
                or any(type(s) is not str or not s for s in self.event_ids)
                or type(self.values) is not tuple or len(self.values) != 2
                or any(type(v) is not int or not 0 <= v < 10 for v in self.values)):
            raise ValueError("Invalid measured paired observation")
        alias = self.event_ids[0] == self.event_ids[1]
        if alias != (self.target // 10 == self.target % 10):
            raise ValueError("Source mechanism differs from the declared alias protocol")
        if alias and self.values[0] != self.values[1]:
            raise ValueError("One deterministic evidence event has contradictory outcomes")
        return self.values[0] if alias else 10 + 10 * self.values[0] + self.values[1]


class JointObservationLaw:
    """Column-stochastic measured joint law; an all-NaN column means unknown."""

    def __init__(self, likelihood, provenance=None):
        matrix = np.asarray(likelihood, dtype=np.float64)
        if matrix.shape != (110, 100):
            raise ValueError("The joint alphabet requires 110 events by 100 targets")
        known = np.isfinite(matrix).all(0)
        unknown = np.isnan(matrix).all(0)
        if not (known | unknown).all():
            raise ValueError("Unknown columns must be wholly unidentified, never partly filled")
        if ((matrix[:, known] < 0).any()
                or not np.allclose(matrix[:, known].sum(0), 1., atol=1e-10, rtol=0.)):
            raise ValueError("Known joint columns must be normalized and nonnegative")
        off_diagonal = [t for t in range(100) if t not in DIAGONAL and known[t]]
        diagonal = [t for t in DIAGONAL if known[t]]
        if (np.any(matrix[:10, off_diagonal] != 0)
                or np.any(matrix[10:, diagonal] != 0)):
            raise ValueError("Joint law violates the declared source mechanism's structural zeros")
        self.likelihood, self.known_targets = matrix.copy(), known.copy()
        self.likelihood.setflags(write=False)
        self.known_targets.setflags(write=False)
        self.provenance = dict(provenance or {})

    @classmethod
    def from_components(cls, single_digit, distinct_joint=None):
        """Repair aliases with one likelihood factor; do not infer missing J_uv."""
        single = np.asarray(single_digit, dtype=np.float64)
        if (single.shape != (10, 10) or not np.isfinite(single).all()
                or (single < 0).any()
                or not np.allclose(single.sum(0), 1., atol=1e-10, rtol=0.)):
            raise ValueError("A supplied single-event conditional law is required")
        matrix = np.full((110, 100), np.nan)
        for digit, target in enumerate(DIAGONAL):
            matrix[:, target] = 0.
            matrix[:10, target] = single[:, digit]
        if distinct_joint is not None and type(distinct_joint) is not dict:
            raise ValueError("Supply explicit target-indexed joint laws, never marginal arrays")
        for target, values in (distinct_joint or {}).items():
            if type(target) is not int or not 0 <= target < 100 or target in DIAGONAL:
                raise ValueError("Only distinct-target joint couplings may be supplied here")
            matrix[:, target] = 0.
            matrix[10:, target] = probability(values)
        return cls(matrix, {"origin": "supplied component laws; empirical transfer unqualified"})

    @classmethod
    def fit_paired(cls, rows, *, alpha, excluded_groups=()):
        """Group-weighted full-joint counts; unsupported targets remain unknown.

        Explicit symmetric smoothing is restricted to structural support and
        does not turn an unobserved target into an identified conditional law.
        Repeated views of an identical measured event pair are counted once.
        """
        if not math.isfinite(alpha) or alpha < 0:
            raise ValueError("Declare finite nonnegative joint-count smoothing")
        unique, sample_ids, event_bindings = {}, set(), {}
        forbidden = set(excluded_groups)
        for row in rows:
            if type(row) is not PairObservation or row.sample_id in sample_ids:
                raise ValueError("Unique measured sample IDs are required")
            sample_ids.add(row.sample_id)
            index = row.outcome_index()
            if row.source_group in forbidden:
                raise ValueError("A reserved source group cannot be used for model fitting")
            for slot, event in enumerate(row.event_ids):
                binding = (row.source_group, row.target // 10 if slot == 0 else row.target % 10,
                           row.values[slot])
                if event in event_bindings and event_bindings[event] != binding:
                    raise ValueError("One evidence event has conflicting source, truth or observation")
                event_bindings[event] = binding
            key = (row.source_group, row.target, row.event_ids)
            if key in unique and unique[key][1] != index:
                raise ValueError("Repeated physical evidence has contradictory observations")
            unique[key] = (row, index)
        if not unique:
            raise ValueError("At least one actual paired observation is required for fitting")
        group_sizes = {}
        for row, _ in unique.values():
            group_sizes[row.source_group] = group_sizes.get(row.source_group, 0) + 1
        matrix, counts = np.full((110, 100), np.nan), np.zeros((110, 100))
        for row, index in unique.values():
            counts[index, row.target] += 1. / group_sizes[row.source_group]
        for target in np.flatnonzero(counts.sum(0) > 0):
            support = slice(0, 10) if target in DIAGONAL else slice(10, 110)
            column = np.zeros(110)
            column[support] = counts[support, target] + alpha
            matrix[:, target] = column / column.sum()
        return cls(matrix, {"origin": "measured paired joint counts", "alpha": alpha,
                   "source_groups": sorted(group_sizes), "physical_pairs": len(unique),
                   "source_rows": len(sample_ids), "statistical_qualification": "not established"})

    def _model(self, prior):
        prior = probability(prior)
        active = np.flatnonzero(prior > 0)
        unknown = active[~self.known_targets[active]]
        if len(unknown):
            raise ValueError(f"Unidentified joint observation columns have positive prior: {unknown.tolist()}")
        targets = tuple(map(int, active))
        model = JointEvidenceModel(targets, ("left", "right"), OUTCOMES,
                                   {t: self.likelihood[:, t] for t in targets})
        return model, {t: float(prior[t]) for t in targets}

    def start_filter(self, prior):
        model, initial = self._model(prior)
        return EvidenceFilter(model, initial)

    def forecast(self, prior):
        """Pre-arrival branches for a controller; no realized identity is supplied."""
        model, initial = self._model(prior)
        p = probability(prior)
        result = []
        for event, (outcome, mass) in enumerate(EvidenceFilter(model, initial).forecast_complete_arrival()):
            if mass <= 0:
                continue
            posterior = np.zeros(100)
            active = np.array(model.targets)
            posterior[active] = p[active] * self.likelihood[event, active] / mass
            result.append({"event": event, "aliases": outcome.aliases, "values": outcome.values,
                           "probability": mass, "posterior": posterior})
        return result

    def export(self):
        return {"schema": SCHEMA, "protocol": PROTOCOL, "events": [
            {"aliases": list(o.aliases), "values": list(o.values)} for o in OUTCOMES],
            "likelihood_by_target": [self.likelihood[:, t].tolist() if self.known_targets[t] else None
                                     for t in range(100)], "provenance": self.provenance}

    @classmethod
    def load(cls, record):
        if record.get("schema") != SCHEMA or record.get("protocol") != PROTOCOL:
            raise ValueError("Unknown joint likelihood schema or source protocol")
        events = [{"aliases": list(o.aliases), "values": list(o.values)} for o in OUTCOMES]
        columns = record.get("likelihood_by_target")
        if record.get("events") != events or type(columns) is not list or len(columns) != 100:
            raise ValueError("The exact event alphabet and target order must be bound")
        return cls(np.array([np.full(110, np.nan) if c is None else c for c in columns]).T,
                   record.get("provenance"))


def arrived_receipts(event_ids, observed_values):
    """Convert actual, post-commit observer output; no paths or truth enter policy."""
    if len(event_ids) != 2 or len(observed_values) != 2:
        raise ValueError("The observed source pair must have two placements")
    return tuple(Receipt(slot, event, value) for slot, event, value in
                 zip(("left", "right"), event_ids, observed_values))
