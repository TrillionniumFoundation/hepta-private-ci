"""A fast host actor fitted to actual joint complete-return action moments.

The positive log-link uses a proper conditional-mean objective. It is a learned
estimate, never a certified moment or a proof of global optimality.
"""

from dataclasses import dataclass
import math

import numpy as np

from ..unified_20261028.profile import digest
from .profile_contract import ACTIONS, FEATURE_DIMENSION


def features(context):
    public = context["emission_public_features"]
    if (len(public) != FEATURE_DIMENSION
            or any(isinstance(v, bool) or not math.isfinite(v) for v in public)):
        raise ValueError("Sixteen finite, public-only features are required")
    return np.asarray([float(context["feedback"]), float(context["owner_abstained"]),
                       float(context["media_units_remaining"]), *public], dtype=np.float64)


def target_moment(value, profile):
    # At gamma=0 the loss is a positive affine transform of -complete return.
    if profile.gamma == 0:
        return profile.utility_bounds[1] - value
    result = math.exp(-profile.gamma * value)
    if not math.isfinite(result):
        raise ValueError("Actual return exceeds the supported numerical scale")
    return result


@dataclass(frozen=True)
class MomentActor:
    profile_sha256: str
    location: tuple[float, ...]
    scale: tuple[float, ...]
    coefficients: tuple[tuple[float, ...], ...]
    training_record_sha256: str
    training_source_ids: tuple[str, ...]
    steps: int

    def to_dict(self):
        return {"schema": "hepta.ndu.complete-action-moment-actor.v1",
                "profile_sha256": self.profile_sha256, "location": self.location,
                "scale": self.scale, "coefficients": self.coefficients,
                "training_record_sha256": self.training_record_sha256,
                "training_source_ids": self.training_source_ids, "steps": self.steps,
                "actions": ACTIONS, "selection": "minimum complete conditional moment; ties keep",
                "estimation": "positive log-link conditional mean; exp(eta)-observed_moment*eta",
                "calibration_status": "requires separate frozen-policy calibration"}

    @property
    def digest(self):
        return digest(self.to_dict())

    @classmethod
    def from_dict(cls, record):
        args = {key: record[key] for key in cls.__dataclass_fields__}
        for name in ("location", "scale", "training_source_ids"):
            args[name] = tuple(args[name])
        args["coefficients"] = tuple(tuple(row) for row in args["coefficients"])
        result = cls(**args)
        if digest(record) != result.digest:
            raise ValueError("Actor serialization or selection semantics changed")
        return result

    def predict(self, context):
        if context["profile_sha256"] != self.profile_sha256:
            raise ValueError("Actor and actual episode optimize different profiles")
        raw = features(context)
        x = np.concatenate(([1.0], (raw - self.location) / self.scale))
        logs = np.asarray(self.coefficients) @ x
        if not np.isfinite(logs).all() or np.max(logs) > 700:
            raise ValueError("Moment prediction is outside its finite numerical domain")
        return {action: float(math.exp(logs[i])) for i, action in enumerate(ACTIONS)}

    def choose(self, context):
        estimates = self.predict(context)
        selected = min(ACTIONS, key=lambda action: estimates[action])
        return selected, {"policy_sha256": self.digest, "predicted_complete_moments": estimates,
                          "selected_action": selected, "moments_are_estimates": True,
                          "private_target_access": False}


def fit_actor(records, profile, *, steps=400, learning_rate=.03):
    """Fit only development/training complete outcomes, never calibration rows.

Each original source receives equal total weight within each action. Repeated
draws increase Monte Carlo precision, not the independent-source count. Rows
must arise from predeclared complete paired interventions or randomized actions.
"""
    rows = list(records)
    if (not rows or isinstance(steps, bool) or not isinstance(steps, int) or steps < 1
            or not math.isfinite(learning_rate) or learning_rate <= 0):
        raise ValueError("Nonempty declared actor training and a valid optimizer are required")
    contexts, event_ids = set(), set()
    for row in rows:
        if (row["profile_sha256"] != profile.digest
                or row["split"] not in {"train", "development"}
                or row["selected_action"] not in ACTIONS
                or row["sampling_design"] not in {"paired_complete_actions", "randomized_actions"}):
            raise ValueError("Actor fitting requires current-profile training interventions")
        if row["event_id"] in event_ids:
            raise ValueError("A repeated execution cannot be counted twice")
        event_ids.add(row["event_id"])
        contexts.add(row["context_id"])
        if not math.isfinite(row["net_return"]):
            raise ValueError("Complete physical return must be finite")
        if row["sampling_design"] == "randomized_actions" and not 0 < row["propensity"] <= 1:
            raise ValueError("Randomized training needs a positive actual action propensity")
    if profile.aggregation == "conditional" and len(contexts) > 1:
        raise ValueError("This actor fitter cannot substitute a pooled population moment for conditional CE")
    raw = np.stack([features(row["boundary_context"]) for row in rows])
    location, scale = raw.mean(0), raw.std(0)
    scale[scale < 1e-8] = 1.0
    x = np.column_stack((np.ones(len(raw)), (raw - location) / scale))
    targets = np.asarray([target_moment(row["net_return"], profile) for row in rows])
    if np.any(targets < 0) or not np.isfinite(targets).all():
        raise ValueError("Actual moment targets must be finite and nonnegative")
    coefficients = []
    diagnostics = {}
    for action in ACTIONS:
        indices = np.asarray([i for i, row in enumerate(rows) if row["selected_action"] == action])
        if len(indices) == 0:
            raise ValueError("Both executable action laws need actual complete observations")
        counts = {}
        for index in indices:
            source = rows[index]["source_id"]
            counts[source] = counts.get(source, 0) + 1
        weights = np.asarray([1 / counts[rows[i]["source_id"]]
                              / (rows[i]["propensity"] if rows[i]["sampling_design"] == "randomized_actions" else 1)
                              for i in indices])
        weights /= weights.sum()
        design, y = x[indices], targets[indices]
        theta = np.zeros(x.shape[1]); theta[0] = math.log(max(float(weights @ y), 1e-12))
        loss_before = float(weights @ (np.exp(design @ theta) - y * (design @ theta)))
        for _ in range(steps):
            eta = design @ theta
            gradient = design.T @ (weights * (np.exp(eta) - y))
            # Bounded optimizer steps protect numerical evaluation; rewards and
            # probabilities remain untouched, and no regularizer is added.
            update = learning_rate * gradient / max(1.0, float(np.linalg.norm(gradient)))
            theta -= update
        eta = design @ theta
        loss_after = float(weights @ (np.exp(eta) - y * eta))
        coefficients.append(tuple(float(v) for v in theta))
        diagnostics[action] = {"executions": len(indices), "source_count": len(counts),
                               "proper_loss_before": loss_before, "proper_loss_after": loss_after,
                               "mean_complete_moment": float(weights @ y)}
    actor = MomentActor(profile.digest, tuple(location), tuple(scale), tuple(coefficients),
                        digest(rows), tuple(sorted({r["source_id"] for r in rows})), steps)
    return actor, {"actions": diagnostics, "actor_sha256": actor.digest,
                   "scope": "conditional moment estimation from full actual trajectories; no optimality certificate"}
