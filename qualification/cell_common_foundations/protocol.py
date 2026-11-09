"""Comparison identity, inclusive accounting, and honest attempt denominators.

This module is an offline research utility, not a new runtime ledger or an
alternative to the existing learning/artifact owners.
"""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path


CELL_ROLES = (
    "perception_encoding",
    "memory_association",
    "prediction_simulation",
    "decision_coordination",
    "verification_risk",
    "tool_action",
    "evaluation_adoption",
)
STATUS_VALUES = {"unstarted", "running", "completed", "failed", "cancelled"}
MATCHED_FIELDS = (
    "encoder_digest",
    "head_initial_digest",
    "data_split_digest",
    "ndu_profile_digest",
    "training_observations",
    "optimizer_updates",
    "tuning_trials",
    "seed",
    "device_profile",
    "precision",
    "training_scope",
)


def canonical_digest(value):
    """Hash finite JSON with stable ordering and no permissive NaN encoding."""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def source_inventory(root, relative_paths):
    """Bind exactly the regular files used by an experiment, excluding outputs."""
    root = Path(root).resolve()
    result = {}
    for relative in sorted(set(relative_paths)):
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source path must be relative and confined")
        candidate = root / path
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("source must be an existing regular file")
        resolved = candidate.resolve()
        if root not in resolved.parents:
            raise ValueError("source escapes experiment root")
        payload = resolved.read_bytes()
        result[path.as_posix()] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
    if not result:
        raise ValueError("empty source inventory")
    return {"files": result, "digest": canonical_digest(result)}


def _nonnegative_finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a finite nonnegative measurement")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative measurement")
    return float(value)


def _count(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class AttemptSpec:
    """One independently declared method/seed opportunity, including failures."""

    attempt_id: str
    family: str
    method: str
    seed: int

    def validate(self):
        if not all(
            isinstance(x, str) and x.strip()
            for x in (self.attempt_id, self.family, self.method)
        ):
            raise ValueError("attempt identities must be nonempty")
        _count(self.seed, "seed")


def compare_profiles(left, right):
    """Reject missing identities and return every declared comparison mismatch."""
    for profile in (left, right):
        if not isinstance(profile, dict):
            raise ValueError("comparison profile must be an object")
        for field in MATCHED_FIELDS:
            if field not in profile or profile[field] is None:
                raise ValueError(f"missing matched field: {field}")
        for field in ("training_observations", "optimizer_updates"):
            _count(profile[field], field, minimum=1)
        _count(profile["tuning_trials"], "tuning_trials")
        _count(profile["seed"], "seed")
        for field in MATCHED_FIELDS:
            if field not in {
                "training_observations",
                "optimizer_updates",
                "tuning_trials",
                "seed",
            }:
                if not isinstance(profile[field], str) or not profile[field].strip():
                    raise ValueError(f"empty comparison identity: {field}")
    mismatches = [field for field in MATCHED_FIELDS if left[field] != right[field]]
    return {"matched": not mismatches, "mismatches": mismatches}


def cost_observation(
    *,
    wall_seconds,
    cpu_seconds,
    peak_rss_bytes=None,
    energy_joules=None,
    energy_sensor=None,
    components=None,
):
    """Preserve missing energy and make measurement coverage explicit.

    Callers must supply disjoint, measured wall-time intervals. The sum check
    rejects obvious overcounting; it cannot prove that intervals do not overlap.
    The remainder is retained as unallocated time.
    RSS is a process high-water mark and cannot be called per-kernel allocation.
    """
    wall = _nonnegative_finite(wall_seconds, "wall_seconds")
    cpu = _nonnegative_finite(cpu_seconds, "cpu_seconds")
    parts = {
        name: _nonnegative_finite(value, name)
        for name, value in (components or {}).items()
    }
    if any(not isinstance(name, str) or not name for name in parts):
        raise ValueError("cost component names must be nonempty")
    if sum(parts.values()) > wall + 1e-8:
        raise ValueError("overlapping or impossible component timing")
    if peak_rss_bytes is not None:
        _count(peak_rss_bytes, "peak_rss_bytes")
    if energy_joules is not None:
        energy_joules = _nonnegative_finite(energy_joules, "energy_joules")
        if not isinstance(energy_sensor, str) or not energy_sensor.strip():
            raise ValueError("energy requires an actual sensor identity")
    elif energy_sensor is not None:
        raise ValueError("sensor identity without energy observation")
    return {
        "wall_seconds": wall,
        "process_cpu_seconds": cpu,
        "peak_process_rss_bytes": peak_rss_bytes,
        "rss_scope": "process_high_water_mark",
        "energy_joules": energy_joules,
        "energy_sensor": energy_sensor,
        "energy_status": "measured" if energy_joules is not None else "unmeasured",
        "component_wall_seconds": parts,
        "unallocated_wall_seconds": max(0.0, wall - sum(parts.values())),
    }


def summarize_attempts(roster, records):
    """Reconcile the entire planned roster without dropping failures or absences.

    Completed means that the declared experiment ran, not that a method improved
    a task or is eligible for adoption. Duplicate outcomes require explicit new
    attempt IDs; they never replace the first attempt.
    """
    planned = {}
    for spec in roster:
        spec.validate()
        if spec.attempt_id in planned:
            raise ValueError("duplicate planned attempt")
        planned[spec.attempt_id] = spec
    if not planned:
        raise ValueError("empty attempt roster")
    observed = {}
    for record in records:
        key = record.get("attempt_id")
        if key not in planned or key in observed:
            raise ValueError("unplanned or duplicate attempt outcome")
        spec = planned[key]
        if any(
            record.get(field) != getattr(spec, field)
            for field in ("family", "method", "seed")
        ):
            raise ValueError("attempt identity changed")
        status = record.get("status")
        if status not in STATUS_VALUES:
            raise ValueError("unknown attempt status")
        if status in {"failed", "cancelled"} and not record.get("reason"):
            raise ValueError("unsuccessful attempt requires its reason")
        if status == "completed":
            if not isinstance(record.get("result"), dict) or not record["result"]:
                raise ValueError("completion requires actual result")
            canonical_digest(record["result"])
        observed[key] = record
    counts = {status: 0 for status in sorted(STATUS_VALUES)}
    for key in planned:
        counts[observed[key]["status"] if key in observed else "unstarted"] += 1
    completed_seeds = {}
    for spec in planned.values():
        completed_seeds.setdefault(f"{spec.family}/{spec.method}", set())
        if observed.get(spec.attempt_id, {}).get("status") == "completed":
            completed_seeds[f"{spec.family}/{spec.method}"].add(spec.seed)
    return {
        "planned_attempts": len(planned),
        "observed_attempts": len(observed),
        "counts": counts,
        "complete": counts["completed"] == len(planned),
        "planned_seed_count": len({x.seed for x in planned.values()}),
        "completed_seed_count_by_family_method": {
            key: len(seeds) for key, seeds in sorted(completed_seeds.items())
        },
        "missing_attempt_ids": sorted(set(planned) - set(observed)),
        "scientific_acceptance": "HOLD",
        "scope": "synthetic_mechanism_reference",
        "production_adoption": "not_granted",
    }
