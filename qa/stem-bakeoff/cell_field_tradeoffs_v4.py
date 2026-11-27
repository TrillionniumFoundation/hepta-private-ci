"""Same-norm direction and fixed-direction amplitude accounting for library49.

All entries remain visible, including failed branches. Quadratic intervention
charges are never reported as CPU, wall time or energy. No policy is selected.
"""

import math

import numpy as np

from cell_field_fixed_actions import fixed_library


def summarize_fixed_actions(rows, *, parameters, dt=0.02, effort_price=0.1):
    """Accept exactly 49 frozen per-anchor records and preserve their full census.

    A row contains action_id, u, status, scores, cpu_ns and wall_ns. Completed
    scores are actual score_common outputs; unavailable scores must be None.
    Timings cover each real branch, excluding shared reference/planning work.
    """
    if (not isinstance(rows, (list, tuple)) or len(rows) != 49
            or not math.isfinite(dt) or not 0 < dt <= 1
            or not math.isfinite(effort_price) or effort_price <= 0):
        raise ValueError("complete fixed-library census and positive finite charges required")
    library = dict(fixed_library(parameters))
    records, order = {}, []
    components = ("direct_current", "forgetting", "effort", "direct_soft_total")
    identities = []
    for row in rows:
        name = row.get("action_id")
        if name not in library or name in records:
            raise ValueError("unknown or duplicate action identity")
        u = np.asarray(row.get("u"), dtype=np.float64)
        if u.shape != (parameters,) or not np.array_equal(u, library[name]):
            raise ValueError("action differs from the predeclared fixed library")
        status = row.get("status")
        if status not in ("completed", "execution_failed", "not_executed", "unresolved"):
            raise ValueError("explicit completed/failed/unavailable status required")
        timing = {key: row.get(key) for key in ("cpu_ns", "wall_ns")}
        if any(v is not None and (type(v) is not int or v < 0) for v in timing.values()):
            raise ValueError("nonnegative measured nanoseconds or explicit None required")
        if status == "completed" and any(v is None for v in timing.values()):
            raise ValueError("completed branches require actual CPU/wall accounting")
        normsquared = float(u @ u)
        expected_effort = 0.5 * dt * effort_price * normsquared
        physical_squared = float((dt * u) @ (dt * u))
        identity = abs(expected_effort - effort_price * physical_squared / (2 * dt))
        item = {"action_id": name, "status": status, "control_norm": math.sqrt(normsquared),
                "physical_impulse_norm": math.sqrt(physical_squared),
                "declared_quadratic_action_penalty": expected_effort, **timing}
        if status == "completed":
            score = row.get("scores")
            if (not isinstance(score, dict) or any(k not in score for k in components)
                    or any(type(score[k]) not in (float, int) or not math.isfinite(score[k]) for k in components)):
                raise ValueError("finite actual risk, forgetting, action penalty and total required")
            residual = score["direct_soft_total"] - sum(score[k] for k in components[:3])
            tolerance = 1e-12 * max(1.0, *(abs(score[k]) for k in components))
            if abs(residual) > tolerance or abs(score["effort"] - expected_effort) > tolerance:
                raise ValueError("actual cost decomposition or physical action identity disagrees")
            item.update({k: float(score[k]) for k in components})
            item["cost_sum_residual"] = residual
            item["terminal_current_nll"] = score.get("terminal_current_nll")
            item["maximum_future_old_excess"] = score.get("maximum_future_old_excess")
            identities.append(max(abs(residual), abs(score["effort"] - expected_effort), identity))
        else:
            if row.get("scores") is not None:
                raise ValueError("failed or unavailable branch cannot carry a completed score")
            item.update({k: None for k in components})
            item["error"] = row.get("error")
        records[name], order = item, order + [name]
    if set(records) != set(library):
        raise ValueError("missing registered action")
    zero = records["zero"]
    for name, item in records.items():
        item["difference_from_zero"] = ({k: item[k] - zero[k] for k in components}
            if item["status"] == zero["status"] == "completed" else None)
    same_norm, amplitude_scans = [], []
    for fraction in ("1/8", "1/2", "1/1"):
        names = [f"d{direction}:a{fraction}:s{polarity}"
                 for direction in range(8) for polarity in (-1, 1)]
        norms = [records[name]["control_norm"] for name in names]
        if max(norms) - min(norms) > 1e-14:
            raise ValueError("same-amplitude directions have unequal actual norms")
        complete = all(records[name]["status"] == "completed" for name in names)
        same_norm.append({"amplitude": fraction, "control_norm": norms[0],
            "complete": complete, "entries": [records[name] for name in names],
            "actual_current_risk_range": ([min(records[name]["direct_current"] for name in names),
                max(records[name]["direct_current"] for name in names)] if complete else None)})
    for direction in range(8):
        for polarity in (-1, 1):
            names = ["zero"] + [f"d{direction}:a{fraction}:s{polarity}" for fraction in ("1/8", "1/2", "1/1")]
            amplitude_scans.append({"direction": direction, "polarity": polarity,
                "complete": all(records[name]["status"] == "completed" for name in names),
                "entries": [records[name] for name in names]})
    return {"schema": "hepta.cell-fixed-action-tradeoffs.v4", "registered": 49,
            "completed": sum(item["status"] == "completed" for item in records.values()),
            "maximum_identity_residual": max(identities, default=None),
            "same_norm_directions": same_norm, "fixed_direction_amplitudes": amplitude_scans,
            "all_actions": [records[name] for name in order],
            "resources": {key: {"observed_total": sum(item[key] for item in records.values() if item[key] is not None),
                "measured_branches": sum(item[key] is not None for item in records.values())}
                for key in ("cpu_ns", "wall_ns")},
            "scope": "one fixed anchor; descriptive finite candidate census; no strategy selection",
            "cost_scope": "measured branch CPU/wall excludes shared preparation; action penalty is a separate objective charge"}
