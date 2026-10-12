"""Pure offline selectors and output checking; no generator/owner replacement.

Utility intervals must come from the caller's fixed registered NDU profile.
This implements ONLY a linear conditional-utility/cost special case. It is
neither a generic FBSDE solver nor an authorization or semantic-truth service.
"""

from dataclasses import dataclass
import hashlib
import math


@dataclass(frozen=True)
class Continuation:
    action: str
    lower: float
    upper: float
    cost: float


def choose_continuation(options, *, stop_utility, remaining_cost):
    """Conservative one-step selector, with a real stop alternative.

    Intervals and hard feasibility are supplied from pre-action history only.
    It does not choose a lucky future leaf or claim global optimal stopping.
    """
    if (not isinstance(options, tuple) or len(options) > 32
            or any(type(x) not in (int, float) or not math.isfinite(x)
                   for x in (stop_utility, remaining_cost)) or remaining_cost < 0):
        raise ValueError("invalid continuation budget")
    names = set()
    eligible = []
    for option in options:
        if (type(option) is not Continuation or type(option.action) is not str
                or not 0 < len(option.action) <= 128 or option.action == "stop"
                or option.action in names
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in (option.lower, option.upper, option.cost))
                or option.lower > option.upper or option.cost < 0):
            raise ValueError("invalid continuation interval")
        names.add(option.action)
        if option.cost <= remaining_cost and option.lower - option.cost > stop_utility:
            eligible.append(option)
    if not eligible:
        return "stop"
    return min(eligible, key=lambda o: (-(o.lower - o.cost), o.action)).action


@dataclass(frozen=True)
class GeneratedOutput:
    attempt_id: str
    modality: str
    request_digest: str
    content: bytes
    content_digest: str
    measured_cost: float


def evaluate_generated_outputs(outputs, *, expected_request_digest, cost_ceiling, verifier):
    """Score actual output bytes with a separately supplied verifier.

    Includes every failed-output attempt in charged cost. No internal NDU score
    can substitute for verification. These are research observations, unsigned.
    No next action is generated here; effectful dispatch belongs to its owner.
    """
    digest_ok = lambda d: type(d) is str and len(d) == 64 and all(c in "0123456789abcdef" for c in d)
    if (not isinstance(outputs, tuple) or not 1 <= len(outputs) <= 32
            or not digest_ok(expected_request_digest)
            or type(cost_ceiling) not in (int, float) or not math.isfinite(cost_ceiling)
            or cost_ceiling < 0):
        raise ValueError("invalid output envelope")
    seen, cost, total_bytes = set(), 0.0, 0
    # Entire batch is validated before a verifier sees any payload.
    for item in outputs:
        if (type(item) is not GeneratedOutput or type(item.attempt_id) is not str
                or not 0 < len(item.attempt_id) <= 128 or item.attempt_id in seen
                or item.modality not in ("text", "image", "video", "audio")
                or item.request_digest != expected_request_digest
                or type(item.content) is not bytes or not 0 < len(item.content) <= 16_777_216
                or hashlib.sha256(item.content).hexdigest() != item.content_digest
                or type(item.measured_cost) not in (int, float)
                or not math.isfinite(item.measured_cost) or item.measured_cost < 0):
            raise ValueError("invalid generated output binding")
        seen.add(item.attempt_id)
        cost += item.measured_cost
        total_bytes += len(item.content)
        if cost > cost_ceiling or total_bytes > 33_554_432:
            raise ValueError("observed output budget exceeded; no acceptance")
    results = []
    for item in outputs:
        try:
            score = verifier(item.modality, item.content)
        except Exception as error:
            results.append({"attempt_id": item.attempt_id, "status": "verifier_failed",
                            "error_type": type(error).__name__, "score": None})
            continue
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("invalid independent output score")
        results.append({"attempt_id": item.attempt_id, "status": "scored", "score": score})
    return {"results": results, "charged_cost": cost, "bytes": total_bytes,
            "independent_attestation_verified": False, "production_authorized": False}


def paired_retention_diagnostic(baseline, candidate, groups, *, minimum_groups, maximum_drop):
    """Descriptive group-level retention only; NEVER a promotion certificate."""
    if (not baseline or len(baseline) != len(candidate) or len(groups) != len(candidate)
            or type(minimum_groups) is not int or minimum_groups < 1
            or type(maximum_drop) not in (int, float) or not math.isfinite(maximum_drop)
            or not 0 <= maximum_drop <= 1):
        raise ValueError("invalid retention census")
    buckets = {}
    for a, b, group in zip(baseline, candidate, groups):
        if (any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in (a, b))
                or type(group) is not str or not group):
            raise ValueError("invalid paired retention row")
        buckets.setdefault(group, []).append(b - a)
    means = {k: sum(v) / len(v) for k, v in buckets.items()}
    enough = len(means) >= minimum_groups
    return {"source_groups": len(means), "group_mean_deltas": means,
            "descriptive_floor_met": enough and all(v >= -maximum_drop for v in means.values()),
            "statistical_superiority_established": False, "production_authorized": False}
