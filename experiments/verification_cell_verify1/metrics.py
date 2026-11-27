"""Descriptive VERIFY-1 measurements; no independence or coverage guarantees.

Outcome labels must be collected for every trajectory, including rejected ones.
Callers own label provenance, inventory completeness and the experimental split.
"""

import math
from collections import Counter
from itertools import combinations


def _fields(row, required, optional=()):
    if not isinstance(row, dict) or not required <= row.keys():
        raise ValueError("row is missing required fields")
    if row.keys() - required - set(optional):
        raise ValueError("row contains unsupported fields")


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _number(value, name, maximum=None):
    if type(value) not in (int, float) or value < 0:
        raise ValueError(f"{name} must be a nonnegative finite number")
    if (type(value) is float and not math.isfinite(value)) or (
        maximum is not None and value > maximum
    ):
        raise ValueError(f"{name} is outside its finite range")


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _boolean(value, name, nullable=False):
    if type(value) is not bool and not (nullable and value is None):
        raise ValueError(f"{name} must be a boolean")


def _digest(value, name):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA256 digest")


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _selection(rows, total):
    count = len(rows)
    errors = sum(r["outcome_error"] is True for r in rows)
    unknown = sum(r["outcome_error"] is None for r in rows)
    return {
        "selected": count,
        "coverage": _ratio(count, total),
        "known_errors": errors,
        "known_labels": count - unknown,
        "unknown_labels": unknown,
        "known_label_error_rate": _ratio(errors, count - unknown),
        "error_rate": _ratio(errors, count) if not unknown else None,
        "error_rate_bounds": [errors / count, (errors + unknown) / count]
        if count
        else None,
    }


def summarize(rows, thresholds=(0.0, 0.1, 0.25, 0.5, 0.75, 1.0)):
    """Report per-arm policy acceptance and separate threshold selections.

    Bounds describe missing labels, not confidence intervals. Detection lead time
    is relative to terminal_step, not to an unobserved irreversible effect.
    Clean-outcome interruptions are descriptive, not proof of causal necessity.
    """
    rows, thresholds = list(rows), tuple(thresholds)
    for threshold in thresholds:
        _number(threshold, "threshold", 1)
    if any(a >= b for a, b in zip(thresholds, thresholds[1:])):
        raise ValueError("thresholds must be strictly increasing")
    required = {
        "trajectory_id",
        "source_group",
        "arm",
        "fault",
        "risk",
        "accepted",
        "outcome_error",
        "injected_step",
        "detected_step",
        "terminal_step",
        "interrupted",
    }
    seen = set()
    for row in rows:
        _fields(row, required)
        for key in ("trajectory_id", "source_group", "arm", "fault"):
            _text(row[key], key)
        identity = row["trajectory_id"], row["arm"]
        if identity in seen:
            raise ValueError("duplicate trajectory_id and arm")
        seen.add(identity)
        _number(row["risk"], "risk", 1)
        _boolean(row["accepted"], "accepted")
        _boolean(row["interrupted"], "interrupted")
        _boolean(row["outcome_error"], "outcome_error", nullable=True)
        _integer(row["terminal_step"], "terminal_step")
        for key in ("injected_step", "detected_step"):
            if row[key] is not None:
                _integer(row[key], key)
                if row[key] > row["terminal_step"]:
                    raise ValueError(f"{key} occurs after terminal_step")
        if row["injected_step"] is not None and row["detected_step"] is not None:
            if row["detected_step"] < row["injected_step"]:
                raise ValueError("detected_step precedes injected_step")
    arms = {}
    for arm in sorted({r["arm"] for r in rows}):
        group = sorted(
            (r for r in rows if r["arm"] == arm), key=lambda r: r["trajectory_id"]
        )
        injected = [r for r in group if r["injected_step"] is not None]
        detected = [r for r in injected if r["detected_step"] is not None]
        clean = [r for r in group if r["outcome_error"] is False]
        clean_interrupted = sum(r["interrupted"] for r in clean)
        sources = sorted({r["source_group"] for r in group})
        arms[arm] = {
            "trajectories": len(group),
            "source_groups": sources,
            "source_group_count": len(sources),
            "fault_counts": dict(sorted(Counter(r["fault"] for r in group).items())),
            "all_trajectories": _selection(group, len(group)),
            "policy_accepted": _selection(
                [r for r in group if r["accepted"]], len(group)
            ),
            "risk_coverage": [
                {
                    "threshold": t,
                    **_selection([r for r in group if r["risk"] <= t], len(group)),
                }
                for t in thresholds
            ],
            "detection": {
                "injected_trajectories": len(injected),
                "detected": len(detected),
                "undetected_trajectory_ids": [
                    r["trajectory_id"] for r in injected if r["detected_step"] is None
                ],
                "detected_without_injection_ids": [
                    r["trajectory_id"]
                    for r in group
                    if r["injected_step"] is None and r["detected_step"] is not None
                ],
                "detected_observations": [
                    {
                        "trajectory_id": r["trajectory_id"],
                        "delay_steps": r["detected_step"] - r["injected_step"],
                        "terminal_lead_steps": r["terminal_step"] - r["detected_step"],
                    }
                    for r in detected
                ],
            },
            "interruptions": {
                "total": sum(r["interrupted"] for r in group),
                "known_clean_trajectories": len(clean),
                "interrupted_known_clean": clean_interrupted,
                "rate_among_known_clean": _ratio(clean_interrupted, len(clean)),
                "interrupted_unknown_outcome": sum(
                    r["interrupted"] and r["outcome_error"] is None for r in group
                ),
            },
        }
    return {
        "descriptive_only": True,
        "threshold_selection": "risk <= threshold across all trajectories; independent of policy acceptance",
        "error_bounds": "missing-label bounds; not confidence intervals",
        "source_group_counts_are_independent_sample_sizes": False,
        "total_rows": len(rows),
        "arms": arms,
    }


def compare_votes(vote_rows):
    """Measure observed co-errors; base/adapter differences are provenance only."""
    rows = list(vote_rows)
    required = {
        "trajectory_id",
        "voter_id",
        "base_sha256",
        "adapter_sha256",
        "output_sha256",
        "vote_error",
        "outcome_error",
    }
    voters, trajectories = {}, {}
    for row in rows:
        _fields(row, required)
        for key in ("trajectory_id", "voter_id"):
            _text(row[key], key)
        for key in ("base_sha256", "output_sha256"):
            _digest(row[key], key)
        if row["adapter_sha256"] is not None:
            _digest(row["adapter_sha256"], "adapter_sha256")
        for key in ("vote_error", "outcome_error"):
            _boolean(row[key], key)
        identity = row["base_sha256"], row["adapter_sha256"]
        voter = row["voter_id"]
        if voter in voters and voters[voter] != identity:
            raise ValueError("voter_id changed base or adapter identity")
        voters[voter] = identity
        panel = trajectories.setdefault(row["trajectory_id"], {})
        if voter in panel:
            raise ValueError("duplicate trajectory_id and voter_id")
        if (
            panel
            and next(iter(panel.values()))["outcome_error"] != row["outcome_error"]
        ):
            raise ValueError("inconsistent outcome labels for one trajectory")
        panel[voter] = row
    pairwise = []
    for left, right in combinations(sorted(voters), 2):
        matched = [
            (tid, panel)
            for tid, panel in sorted(trajectories.items())
            if left in panel and right in panel
        ]
        cells = Counter(
            (panel[left]["vote_error"], panel[right]["vote_error"])
            for _, panel in matched
        )
        n00, n01, n10, n11 = (
            cells[a, b]
            for a, b in ((False, False), (False, True), (True, False), (True, True))
        )
        denominator = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
        relation = "different_base"
        if voters[left][0] == voters[right][0]:
            relation = (
                "same_base_same_adapter"
                if voters[left][1] == voters[right][1]
                else "same_base_different_adapter"
            )
        pairwise.append(
            {
                "left": left,
                "right": right,
                "provenance_relation": relation,
                "paired_trajectory_ids": [tid for tid, _ in matched],
                "paired_trajectories": len(matched),
                "both_correct": n00,
                "left_only_error": n10,
                "right_only_error": n01,
                "both_error": n11,
                "error_phi": (n11 * n00 - n10 * n01) / denominator
                if denominator
                else None,
            }
        )
    clusters = []
    for tid, panel in sorted(trajectories.items()):
        wrong = sorted(voter for voter, row in panel.items() if row["vote_error"])
        if len(wrong) >= 2:
            output_groups = {}
            for voter in wrong:
                output_groups.setdefault(panel[voter]["output_sha256"], []).append(
                    voter
                )
            clusters.append(
                {
                    "trajectory_id": tid,
                    "outcome_error": next(iter(panel.values()))["outcome_error"],
                    "voter_ids": wrong,
                    "shared_wrong_outputs": [
                        {"output_sha256": digest, "voter_ids": ids}
                        for digest, ids in sorted(output_groups.items())
                        if len(ids) >= 2
                    ],
                }
            )
    return {
        "descriptive_only": True,
        "independence_established": False,
        "observations": len(rows),
        "trajectories": len(trajectories),
        "voter_provenance": {
            voter: {"base_sha256": base, "adapter_sha256": adapter}
            for voter, (base, adapter) in sorted(voters.items())
        },
        "incomplete_panel_trajectory_ids": [
            tid
            for tid, panel in sorted(trajectories.items())
            if len(panel) != len(voters)
        ],
        "pairwise": pairwise,
        "cofailure_clusters": clusters,
    }


def _finite_sum(values):
    total = sum(values)
    if type(total) is float and not math.isfinite(total):
        raise ValueError("measurement sum exceeds finite numeric range")
    return total


def _cost_group(rows):
    energies = [r["energy_joules"] for r in rows if r.get("energy_joules") is not None]
    measured = _finite_sum(energies) if energies else None
    return {
        "operations": len(rows),
        "summed_operation_wall_ns": sum(r["wall_ns"] for r in rows),
        "summed_operation_cpu_ns": sum(r["cpu_ns"] for r in rows),
        "units_by_kind": {
            kind: _finite_sum(r["units"] for r in rows if r["kind"] == kind)
            for kind in sorted({r["kind"] for r in rows})
        },
        "status_counts": dict(sorted(Counter(r["status"] for r in rows).items())),
        "energy_joules": measured if len(energies) == len(rows) else None,
        "known_energy_joules": measured,
        "energy_known_operations": len(energies),
        "energy_unknown_operations": len(rows) - len(energies),
    }


def summarize_costs(cost_rows):
    """Sum each supplied physical operation once, retaining every status.

    IDs must identify actual executions, including failed/retried executions.
    Parent and child durations may overlap: their sum is not elapsed time.
    Unknown energy stays unknown. Units are summed only within the same kind.
    """
    rows = list(cost_rows)
    required = {
        "operation_id",
        "trajectory_id",
        "arm",
        "kind",
        "wall_ns",
        "cpu_ns",
        "units",
        "status",
    }
    seen = set()
    for row in rows:
        _fields(row, required, optional=("energy_joules",))
        for key in ("operation_id", "trajectory_id", "arm", "kind", "status"):
            _text(row[key], key)
        if row["operation_id"] in seen:
            raise ValueError("duplicate physical operation_id")
        seen.add(row["operation_id"])
        for key in ("wall_ns", "cpu_ns"):
            _integer(row[key], key)
        _number(row["units"], "units")
        if row.get("energy_joules") is not None:
            _number(row["energy_joules"], "energy_joules")
    return {
        "totals": _cost_group(rows),
        "by_arm": {
            arm: _cost_group([r for r in rows if r["arm"] == arm])
            for arm in sorted({r["arm"] for r in rows})
        },
        "by_kind": {
            kind: _cost_group([r for r in rows if r["kind"] == kind])
            for kind in sorted({r["kind"] for r in rows})
        },
        "duration_interpretation": "sum of supplied operation durations; not elapsed time; nesting may overlap",
        "inventory_completeness": "not established by measurement rows alone",
    }
