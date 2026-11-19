"""Frozen registrations, bounded evidence input and proper prediction scores."""

from collections import Counter, defaultdict
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import time

from .trajectory import is_digest


REGISTRATION_SCHEMA = "ndu.stopped.calibration-registration.v1"


ROLES = ("fit", "calibration", "diagnostic")


def _number(value):
    if type(value) not in (int, float):
        raise ValueError("Expected a finite numerical diagnostic value")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(
            "Diagnostic value exceeds the finite numerical domain"
        ) from error
    if not math.isfinite(result):
        raise ValueError("Expected a finite numerical diagnostic value")
    return result


def validate_registration(value):
    required = {
        "schema",
        "fit_source_groups",
        "calibration_source_groups",
        "diagnostic_source_groups",
        "core",
        "memory_mode",
        "seed",
        "neighbor_groups",
        "particles",
        "risk_settings",
        "feature_scales",
        "behavior_was_unfitted_collector",
    }
    defaults = {
        "max_distance": 2.0,
        "max_per_group": 32,
        "latency_weight": 0.01,
        "discount_per_second": 1.0,
        "practical_margin": 0.0,
    }
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or set(value) - required - set(defaults)
    ):
        raise ValueError("Registration fields differ from the fixed diagnostic schema")
    if (
        value["schema"] != REGISTRATION_SCHEMA
        or type(value["behavior_was_unfitted_collector"]) is not bool
    ):
        raise ValueError("Invalid registration schema or collector disposition")
    result, seen = {**defaults, **value}, set()
    for role in ROLES:
        groups = value[role + "_source_groups"]
        if (
            not isinstance(groups, list)
            or len(groups) > 2048
            or (not groups and role != "fit")
            or any(not isinstance(x, str) or not 1 <= len(x) <= 256 for x in groups)
            or len(set(groups)) != len(groups)
            or set(groups) & seen
        ):
            raise ValueError("Source roles must be bounded, explicit and disjoint")
        seen.update(groups)
    if not value["fit_source_groups"] and not value["behavior_was_unfitted_collector"]:
        raise ValueError(
            "An empty fit roster requires an explicitly unfitted collector"
        )
    if (
        not isinstance(value["core"], str)
        or value["core"] not in {"ordinary", "hepta"}
        or not isinstance(value["memory_mode"], str)
        or value["memory_mode"] not in {"reset", "persistent"}
    ):
        raise ValueError("Unknown frozen content or memory profile")
    for key, low, high in (
        ("seed", 0, 2**64 - 1),
        ("neighbor_groups", 2, 64),
        ("particles", 2, 8),
        ("max_per_group", 1, 64),
    ):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError("Invalid bounded registration " + key)
    risks, scales = value["risk_settings"], value["feature_scales"]
    if (
        not isinstance(risks, list)
        or not 1 <= len(risks) <= 8
        or any(not 0 <= _number(x) <= 100 for x in risks)
        or len(set(risks)) != len(risks)
    ):
        raise ValueError("Invalid preregistered risk roster")
    if (
        not isinstance(scales, list)
        or not 1 <= len(scales) <= 256
        or any(_number(x) <= 0 for x in scales)
    ):
        raise ValueError("Invalid preregistered public feature scales")
    if (
        _number(result["max_distance"]) <= 0
        or not 0 < _number(result["discount_per_second"]) <= 1
    ):
        raise ValueError("Invalid support radius or duration discount")
    if any(
        not 0 <= _number(result[k]) <= 1 for k in ("latency_weight", "practical_margin")
    ):
        raise ValueError("Invalid latency penalty or practical threshold")
    return result


def weighted_crps(values, probabilities, observed):
    """Exact CRPS for a finite weighted scalar predictive distribution."""
    x, p, y = tuple(values), tuple(probabilities), _number(observed)
    if not 1 <= len(x) <= 64 or len(x) != len(p):
        raise ValueError("Invalid bounded empirical distribution")
    x, p = tuple(_number(v) for v in x), tuple(_number(v) for v in p)
    total = math.fsum(p)
    if min(p) < 0 or not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Predictive probabilities do not sum to one")
    p = tuple(v / total for v in p)
    result = math.fsum(w * abs(v - y) for v, w in zip(x, p)) - 0.5 * math.fsum(
        p[i] * p[j] * abs(x[i] - x[j]) for i in range(len(x)) for j in range(len(x))
    )
    if not math.isfinite(result) or result < -1e-10:
        raise ValueError("CRPS exceeds its finite numerical domain")
    return max(0.0, result)


def _unique(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Duplicate input JSON field")
    return value


def _json(raw):
    def invalid_constant(value):
        raise ValueError("Nonfinite input JSON number: " + value)

    return json.loads(raw, object_pairs_hook=_unique, parse_constant=invalid_constant)


def _pinned_json(path, digest):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 4 * 1024 * 1024
    ):
        raise ValueError("Pinned metadata is outside the regular-file byte bound")
    raw = path.read_bytes()
    if not is_digest(digest) or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Pinned metadata bytes differ")
    return _json(raw)


def _records(path, digest, budget, *, selected_weights=None):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 512 * 1024 * 1024
    ):
        raise ValueError("Records exceed their regular-file byte bound")
    rows, full, selected, counts = [], hashlib.sha256(), hashlib.sha256(), Counter()
    with path.open("rb") as stream:
        while raw := stream.readline(2 * 1024 * 1024 + 1):
            budget.check()
            counts["input_records"] += 1
            if (
                len(raw) > 2 * 1024 * 1024
                or counts["input_records"] > 10000
                or not raw.strip()
            ):
                raise ValueError("Original record line/count bound exceeded")
            full.update(raw)
            row = _json(raw)
            if not isinstance(row, dict) or row.get("split") != "train":
                raise ValueError(
                    "Only original train records can enter this diagnostic"
                )
            if selected_weights is None:
                rows.append(row)
            elif row.get("behavior_weights_sha256") == selected_weights:
                selected.update(raw)
                counts["selected_records"] += 1
            else:
                counts["excluded_other_behavior_records"] += 1
    if not is_digest(digest) or full.hexdigest() != digest:
        raise ValueError("Original records SHA256 differs")
    return rows, {
        **counts,
        "sha256": full.hexdigest(),
        "bytes": path.stat().st_size,
        "selected_raw_lines_sha256": selected.hexdigest() if selected_weights else None,
    }


class Budget:
    def __init__(self, seconds):
        if not 0 < _number(seconds) <= 1800:
            raise ValueError("Diagnostic wall budget must be at most 1800 seconds")
        self.started, self.cpu_started = time.perf_counter(), time.process_time()
        self.deadline, self.stages = self.started + seconds, []

    def check(self):
        if time.perf_counter() > self.deadline:
            raise TimeoutError("Original diagnostic wall budget exhausted")

    @contextmanager
    def stage(self, name):
        self.check()
        started, cpu, status = time.perf_counter(), time.process_time(), "failed"
        try:
            yield
            self.check()
            status = "completed"
        finally:
            self.stages.append(
                {
                    "name": name,
                    "status": status,
                    "wall_seconds": time.perf_counter() - started,
                    "process_cpu_seconds": time.process_time() - cpu,
                }
            )


def _write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def _aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        if row["status"] == "supported":
            groups[(row["action"], row["source_group"])].append(row["metrics"])
    by_group = []
    for (action, group), values in sorted(groups.items()):
        by_group.append(
            {
                "action": action,
                "source_group": group,
                "macros": len(values),
                "metrics": {
                    m: {
                        law: math.fsum(v[m][law] for v in values) / len(values)
                        for law in ("center", "joint")
                    }
                    for m in ("quality_crps", "duration_crps", "net_crps")
                },
            }
        )
    by_action = []
    for action in sorted({row["action"] for row in by_group}):
        values = [row["metrics"] for row in by_group if row["action"] == action]
        by_action.append(
            {
                "action": action,
                "source_groups": len(values),
                "metrics": {
                    m: {
                        law: math.fsum(v[m][law] for v in values) / len(values)
                        for law in ("center", "joint")
                    }
                    for m in ("quality_crps", "duration_crps", "net_crps")
                },
            }
        )
    return {
        "by_action_and_source_group": by_group,
        "equal_source_group_means_by_action": by_action,
        "paired_support_only": True,
        "independent_training_repeats": 0,
    }
