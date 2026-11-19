"""Bounded joint residuals for a frozen predictor, conditional on public state.

This nearest-neighbor empirical model has no distribution-free conditional
coverage guarantee. Declared source groups establish no authenticated custody.
Outcome labels enter only offline fitting, never the online query interface.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
import copy
import math
import random
from types import MappingProxyType

from .controllers import ACTIONS
from .objective import canonical_sha

SCHEMA = "ndu.conditional-residual-bank.v1"
BINDING_FIELDS = {"weights_sha256", "source_sha256", "profile_sha256"}
RECORD_FIELDS = {
    "public_features",
    "action",
    "predicted_next_features",
    "observed_next_features",
    "predicted_duration_seconds",
    "observed_duration_seconds",
    "predicted_utility",
    "observed_utility",
    "source_group",
    "split",
}


def _number(value):
    if type(value) not in (int, float):
        raise ValueError("Only finite numerical calibration values are accepted")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError("Calibration number exceeds the finite domain") from error
    if not math.isfinite(number):
        raise ValueError("Only finite numerical calibration values are accepted")
    return number


def _vector(value, width):
    if not isinstance(value, (list, tuple)) or len(value) != width:
        raise ValueError("Calibration feature width differs")
    return tuple(_number(x) for x in value)


def _group(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ValueError("Invalid declared source group")
    return value


@dataclass(frozen=True)
class JointResidual:
    state_residual: tuple
    log_duration_residual: float
    utility_residual: float
    probability: float


class UnsupportedCondition(ValueError):
    """The valid query lacks sufficient nearby empirical action support."""


class ConditionalResidualBank:
    """A digest-pinned empirical artifact; construction always validates its body."""

    def __init__(self, document, *, expected_sha256, expected_binding):
        if not isinstance(document, dict):
            raise ValueError("A conditional bank document is required")
        if canonical_sha(document) != expected_sha256:
            raise ValueError("Conditional bank digest differs from its external pin")
        if (
            set(document)
            != {
                "schema",
                "binding",
                "fit_source_groups",
                "feature_scale",
                "neighbor_groups",
                "min_groups",
                "max_per_group",
                "max_distance",
                "rows",
            }
            or document["schema"] != SCHEMA
        ):
            raise ValueError("Unknown conditional bank schema")
        binding = document["binding"]
        if (
            not isinstance(binding, dict)
            or binding != expected_binding
            or set(binding) != BINDING_FIELDS
        ):
            raise ValueError("Frozen predictor/source/profile binding differs")
        for digest in binding.values():
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or set(digest) - set("0123456789abcdef")
                or digest == "0" * 64
            ):
                raise ValueError("Invalid frozen identity digest")
        fits = document["fit_source_groups"]
        if not isinstance(fits, list) or not 1 <= len(fits) <= 2048:
            raise ValueError("A bounded declared fit group roster is required")
        if len({_group(x) for x in fits}) != len(fits):
            raise ValueError("Repeated fit source group")
        scales = document["feature_scale"]
        if not isinstance(scales, list) or not 1 <= len(scales) <= 256:
            raise ValueError("Invalid public feature dimension")
        self._scale = _vector(scales, len(scales))
        if min(self._scale) <= 0:
            raise ValueError("Frozen feature scales must be positive")
        for key, lower, upper in (
            ("neighbor_groups", 2, 64),
            ("min_groups", 2, 64),
            ("max_per_group", 1, 64),
        ):
            if type(document[key]) is not int or not lower <= document[key] <= upper:
                raise ValueError("Invalid bounded calibration " + key)
        if document["neighbor_groups"] < document["min_groups"]:
            raise ValueError("Neighbor group count is below the minimum support")
        if _number(document["max_distance"]) <= 0:
            raise ValueError("Maximum public feature distance must be positive")
        rows = document["rows"]
        if (
            not isinstance(rows, list)
            or not 1 <= len(rows) <= 8192
            or len(rows) * len(scales) > 262144
        ):
            raise ValueError("Calibration bank exceeds its bounded record capacity")
        counts, by_action = Counter(), defaultdict(lambda: defaultdict(list))
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row)
                != {
                    "public_features",
                    "action",
                    "source_group",
                    "split",
                    "state_residual",
                    "log_duration_residual",
                    "utility_residual",
                }
                or row["split"] != "calibration"
            ):
                raise ValueError("Only calibration records may enter the bank")
            group = _group(row["source_group"])
            if group in fits:
                raise ValueError("Fit and calibration source groups overlap")
            counts[group] += 1
            if counts[group] > document["max_per_group"] or len(counts) > 2048:
                raise ValueError("Calibration source group capacity exceeded")
            if row["action"] not in ACTIONS:
                raise ValueError("Unsupported calibration transition action")
            features = _vector(row["public_features"], len(scales))
            residual = JointResidual(
                _vector(row["state_residual"], len(scales)),
                _number(row["log_duration_residual"]),
                _number(row["utility_residual"]),
                1.0,
            )
            if abs(residual.utility_residual) > 1:
                raise ValueError("Utility residual exceeds the frozen unit range")
            by_action[row["action"]][group].append((features, residual))
        self._by_action = MappingProxyType(
            {
                action: MappingProxyType(
                    {group: tuple(rows) for group, rows in groups.items()}
                )
                for action, groups in by_action.items()
            }
        )
        self._document = copy.deepcopy(document)
        self._sha256 = expected_sha256

    @property
    def sha256(self):
        return self._sha256

    @property
    def binding(self):
        return MappingProxyType(self._document["binding"])

    @property
    def scale(self):
        return self._scale

    @classmethod
    def fit(
        cls,
        records,
        *,
        binding,
        fit_source_groups,
        feature_scale,
        neighbor_groups=8,
        min_groups=2,
        max_per_group=32,
        max_distance=2.0,
    ):
        """Fit from observed, source-disjoint calibration transitions only.

        Scales and neighbor settings must be selected without confirmation
        outcomes. Group counts are capped by rejection, never silent truncation.
        """
        if not isinstance(records, (list, tuple)) or not 1 <= len(records) <= 8192:
            raise ValueError("A bounded calibration record sequence is required")
        if (
            not isinstance(fit_source_groups, (list, tuple, set))
            or not 1 <= len(fit_source_groups) <= 2048
        ):
            raise ValueError("A bounded declared fit group roster is required")
        if not isinstance(binding, dict):
            raise ValueError("A frozen identity binding is required")
        if (
            not isinstance(feature_scale, (list, tuple))
            or not 1 <= len(feature_scale) <= 256
        ):
            raise ValueError("Invalid public feature dimension")
        width, rows = len(feature_scale), []
        if len(records) * width > 262144:
            raise ValueError("Calibration bank exceeds its bounded record capacity")
        for record in records:
            if (
                not isinstance(record, dict)
                or set(record) != RECORD_FIELDS
                or record["split"] != "calibration"
            ):
                raise ValueError(
                    "Only exact calibration transition records are accepted"
                )
            before = _vector(record["public_features"], width)
            predicted = _vector(record["predicted_next_features"], width)
            observed = _vector(record["observed_next_features"], width)
            durations = [
                _number(record[key])
                for key in ("predicted_duration_seconds", "observed_duration_seconds")
            ]
            utilities = [
                _number(record[key])
                for key in ("predicted_utility", "observed_utility")
            ]
            if min(durations) <= 0 or not all(0 <= x <= 1 for x in utilities):
                raise ValueError("Invalid duration or unit-range utility observation")
            rows.append(
                {
                    "public_features": list(before),
                    "action": record["action"],
                    "source_group": record["source_group"],
                    "split": "calibration",
                    "state_residual": [b - a for a, b in zip(predicted, observed)],
                    "log_duration_residual": math.log(durations[1])
                    - math.log(durations[0]),
                    "utility_residual": utilities[1] - utilities[0],
                }
            )
        document = {
            "schema": SCHEMA,
            "binding": dict(binding),
            "fit_source_groups": sorted(fit_source_groups),
            "feature_scale": list(feature_scale),
            "neighbor_groups": neighbor_groups,
            "min_groups": min_groups,
            "max_per_group": max_per_group,
            "max_distance": max_distance,
            "rows": rows,
        }
        return cls(
            document, expected_sha256=canonical_sha(document), expected_binding=binding
        )

    @classmethod
    def from_dict(cls, document, *, expected_sha256, expected_binding):
        return cls(
            document, expected_sha256=expected_sha256, expected_binding=expected_binding
        )

    def to_dict(self):
        return copy.deepcopy(self._document)

    def sample(self, public_features, action, *, particles, seed):
        """Query with current public numbers only; no targets or source IDs.

        Groups are equal-weighted and sampled without replacement when the
        particle cap is smaller than the neighbor roster. Within each chosen
        group, draw among equally nearest rows. Joint residual coordinates
        stay paired. These stratified draws are not independent samples.
        """
        features = _vector(public_features, len(self.scale))
        if type(particles) is not int or not 2 <= particles <= 64:
            raise ValueError("Conditional risk requires between 2 and 64 particles")
        if type(seed) is not int or not 0 <= seed < 2**64:
            raise ValueError("Invalid fixed calibration sampling seed")
        if not isinstance(action, str):
            raise ValueError("An action name is required")
        if action not in self._by_action:
            raise UnsupportedCondition("Unsupported calibration transition action")
        groups = self._by_action.get(action, {})
        neighbors = []
        for group, rows in groups.items():
            distances = [
                math.hypot(*((a - b) / s for a, b, s in zip(features, x, self.scale)))
                / math.sqrt(len(features))
                for x, _ in rows
            ]
            distance = min(distances)
            if math.isfinite(distance) and distance <= self._document["max_distance"]:
                nearest = [r for d, (_, r) in zip(distances, rows) if d == distance]
                neighbors.append((distance, group, nearest))
        neighbors.sort(key=lambda item: (item[0], item[1]))
        neighbors = neighbors[: self._document["neighbor_groups"]]
        if len(neighbors) < self._document["min_groups"]:
            raise UnsupportedCondition(
                "Insufficient nearby calibration source groups for action"
            )
        rng = random.Random(seed)
        selected = rng.sample(neighbors, min(particles, len(neighbors)))
        samples = []
        for index, (_, _, residuals) in enumerate(selected):
            count = particles // len(selected) + int(index < particles % len(selected))
            for _ in range(count):
                residual = rng.choice(residuals)
                samples.append(
                    JointResidual(
                        residual.state_residual,
                        residual.log_duration_residual,
                        residual.utility_residual,
                        1 / (len(selected) * count),
                    )
                )
        support = {
            (x.state_residual, x.log_duration_residual, x.utility_residual)
            for x in samples
        }
        return tuple(samples), {
            "schema": SCHEMA,
            "bank_sha256": self.sha256,
            "nearby_source_groups": len(neighbors),
            "sampled_source_groups": len(selected),
            "particles": len(samples),
            "distinct_joint_residuals": len(support),
            "risk_sensitive_support": len(support) > 1,
            "nearest_group_distance": neighbors[0][0],
            "farthest_group_distance": neighbors[-1][0],
            "sampling": "equal_group_mass_nearest_rows_stratified_not_iid",
            "conditional_coverage_established": False,
        }
