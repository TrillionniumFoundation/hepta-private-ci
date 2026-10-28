"""Source-uniform empirical complete-action moments at an observable boundary.

This lower-capacity actor is specified from training evidence. It keeps failure,
refusal and cost branches joint. No development or qualification row is fitted.
"""

from dataclasses import dataclass
import math

from ..unified_20261028.profile import digest
from .control_actor import features, target_moment
from .profile_contract import ACTIONS


def stratum(context):
    features(context)
    return f"feedback={int(context['feedback'])};abstained={int(context['owner_abstained'])};slots={int(context['media_units_remaining'] > 0)}"


@dataclass(frozen=True)
class TableActor:
    profile_sha256: str
    cells: tuple[tuple[str, tuple[float, float]], ...]
    fallback: tuple[float, float]
    training_record_sha256: str
    training_source_ids: tuple[str, ...]

    @property
    def digest(self):
        return digest(self.to_dict())

    def to_dict(self):
        return {"schema": "hepta.ndu.source-uniform-complete-moment-table.v1",
                "profile_sha256": self.profile_sha256, "cells": self.cells, "fallback": self.fallback,
                "training_record_sha256": self.training_record_sha256,
                "training_source_ids": self.training_source_ids,
                "strata": "arrived transport feedback, unchanged owner abstention and remaining media slots",
                "estimation": "within-action equal original-source weight, then equal draws per source",
                "unseen_stratum": "pooled actual training-source complete moment for each action",
                "selection": "minimum complete estimated moment; ties keep", "actions": ACTIONS,
                "confidence_bound_claim": False}

    @classmethod
    def from_dict(cls, record):
        obj = cls(record["profile_sha256"], tuple((key, tuple(value)) for key, value in record["cells"]),
                  tuple(record["fallback"]), record["training_record_sha256"], tuple(record["training_source_ids"]))
        if obj.digest != digest(record):
            raise ValueError("Frozen table policy semantics changed")
        return obj

    def predict(self, context):
        if context["profile_sha256"] != self.profile_sha256:
            raise ValueError("Actual episode and learned table have different profiles")
        values = dict(self.cells).get(stratum(context), self.fallback)
        return dict(zip(ACTIONS, values))

    def choose(self, context):
        predicted = self.predict(context)
        selected = min(ACTIONS, key=lambda action: predicted[action])
        return selected, {"policy_sha256": self.digest, "predicted_complete_moments": predicted,
                          "selected_action": selected, "moments_are_estimates": True,
                          "stratum": stratum(context), "stratum_seen": stratum(context) in dict(self.cells),
                          "private_target_access": False}


def fit_table(records, profile):
    rows = list(records)
    if not rows or len({r["event_id"] for r in rows}) != len(rows):
        raise ValueError("Nonempty unique actual training executions are required")
    if any(r["split"] != "train" or r["profile_sha256"] != profile.digest
           or r["sampling_design"] != "paired_complete_actions" for r in rows):
        raise ValueError("Only preregistered actual training action interventions may fit this actor")
    if profile.aggregation == "conditional" and len({r["context_id"] for r in rows}) > 1:
        raise ValueError("Do not pool different conditional CE contexts")

    def estimate(subset, action):
        by_source = {}
        for row in subset:
            if row["selected_action"] == action:
                by_source.setdefault(row["source_id"], []).append(target_moment(row["net_return"], profile))
        if not by_source:
            return None
        per_source = [math.fsum(values) / len(values) for values in by_source.values()]
        return math.fsum(per_source) / len(per_source)

    fallback = tuple(estimate(rows, action) for action in ACTIONS)
    if any(value is None for value in fallback):
        raise ValueError("Both complete action laws need actual observations")
    cells, diagnostics = [], {}
    for key in sorted({stratum(row["boundary_context"]) for row in rows}):
        subset = [r for r in rows if stratum(r["boundary_context"]) == key]
        values = tuple(estimate(subset, action) for action in ACTIONS)
        if any(value is None for value in values):
            values = fallback
        cells.append((key, values))
        diagnostics[key] = {"complete_moments": dict(zip(ACTIONS, values)),
                            "actions": {action: {"executions": sum(r["selected_action"] == action for r in subset),
                                                 "original_sources": len({r["source_id"] for r in subset if r["selected_action"] == action})}
                                        for action in ACTIONS}}
    actor = TableActor(profile.digest, tuple(cells), fallback, digest(rows),
                       tuple(sorted({row["source_id"] for row in rows})))
    return actor, {"actor_sha256": actor.digest, "cells": diagnostics,
                   "development_and_qualification_used_to_fit": False,
                   "scope": "estimated complete conditional moments, not a certificate of optimality"}
