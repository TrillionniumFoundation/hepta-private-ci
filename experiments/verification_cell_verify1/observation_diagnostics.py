"""Finite-roster observability and calibration diagnostics, never admission.

Features are a caller-frozen projection of public boolean signals. Identity,
fault and terminal labels must not enter that projection. These checks reject
strings and late observations, but cannot authenticate the projection or clocks.
The caller retains an independently frozen roster, original observations and
complete costs. An empirical cell oracle is optimistic on these observed rows;
it is neither a future-information oracle nor evidence of generalization.
"""

from collections import Counter, defaultdict
from itertools import islice
import math


_FIELDS = set(
    "case_id source_group phase view_kind feature_key terminal_error "
    "risk_probability decision available_step decision_step "
    "model_sha256 input_schema_sha256".split()
)
_PHASES = ("train", "cal", "confirm", "shift")


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _validate(rows, bins):
    if not 2 <= len(bins) <= 21 or bins[0] != 0 or bins[-1] != 1:
        raise ValueError("frozen bins must span zero to one")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in bins):
        raise ValueError("invalid frozen bin edge")
    if any(a >= b for a, b in zip(bins, bins[1:])):
        raise ValueError("frozen bins must be strictly increasing")
    if not 0 < len(rows) <= 100000:
        raise ValueError("bounded nonempty observation roster required")
    seen, sources, cases, scopes, widths = set(), {}, {}, {}, {}
    for row in rows:
        if type(row) is not dict or set(row) != _FIELDS:
            raise ValueError("observation fields changed")
        for key in ("case_id", "source_group"):
            value = row[key]
            if (
                type(value) is not str
                or not 0 < len(value) <= 256
                or value != value.strip()
            ):
                raise ValueError("invalid observation identity")
        phase, view = row["phase"], row["view_kind"]
        if phase not in _PHASES or view not in ("ack", "readback"):
            raise ValueError("unknown phase or public view")
        key = (row["case_id"], view)
        if key in seen:
            raise ValueError("duplicate case and view")
        seen.add(key)
        source = row["source_group"]
        if sources.setdefault(source, phase) != phase:
            raise ValueError("source leaks across phases")
        if (
            row["terminal_error"] is not None
            and type(row["terminal_error"]) is not bool
        ):
            raise ValueError("terminal labels must be bool or explicit unknown")
        identity = (source, phase, row["terminal_error"])
        if cases.setdefault(row["case_id"], identity) != identity:
            raise ValueError("case binding or terminal label changed between views")
        for name in ("model_sha256", "input_schema_sha256"):
            value = row[name]
            if (
                type(value) is not str
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError("invalid frozen model or schema digest")
        scope = (row["model_sha256"], row["input_schema_sha256"])
        if scopes.setdefault((phase, view), scope) != scope:
            raise ValueError("mixed model or schema within a phase and view")
        features = row["feature_key"]
        if (
            type(features) not in (list, tuple)
            or len(features) > 16
            or any(x is not None and type(x) is not bool for x in features)
        ):
            raise ValueError("only frozen public bool or unknown signals are allowed")
        if widths.setdefault((view, scope[1]), len(features)) != len(features):
            raise ValueError("feature width changed under one schema")
        probability = row["risk_probability"]
        if probability is not None and (
            type(probability) not in (int, float) or not 0 <= probability <= 1
        ):
            raise ValueError("invalid risk probability")
        if row["decision"] not in ("check", "skip"):
            raise ValueError("unsupported shadow decision")
        if (
            any(
                type(row[k]) is not int or row[k] < 0
                for k in ("available_step", "decision_step")
            )
            or row["available_step"] > row["decision_step"]
        ):
            raise ValueError("observation is not available at decision time")


def _metrics(rows, bins):
    known = [r for r in rows if r["terminal_error"] is not None]
    scored = [r for r in known if r["risk_probability"] is not None]
    errors = sum(r["terminal_error"] for r in known)
    missed = sum(r["terminal_error"] and r["decision"] == "skip" for r in known)
    alarms = sum(not r["terminal_error"] and r["decision"] == "check" for r in known)
    reliability = []
    for lower, upper in zip(bins, bins[1:]):
        selected = [
            r
            for r in rows
            if r["risk_probability"] is not None
            and lower <= r["risk_probability"] <= upper
            and (r["risk_probability"] < upper or upper == 1)
        ]
        labeled = [r for r in selected if r["terminal_error"] is not None]
        count = len(labeled)
        reliability.append(
            {
                "interval": [lower, upper],
                "predictions": len(selected),
                "known_labels": count,
                "unknown_labels": len(selected) - count,
                "mean_risk_known": _ratio(
                    sum(r["risk_probability"] for r in labeled), count
                ),
                "error_rate_known": _ratio(
                    sum(r["terminal_error"] for r in labeled), count
                ),
            }
        )
    missing_skips = sum(
        r["terminal_error"] is None and r["decision"] == "skip" for r in rows
    )
    return {
        "rows": len(rows),
        "known_labels": len(known),
        "unknown_labels": len(rows) - len(known),
        "predictions": sum(r["risk_probability"] is not None for r in rows),
        "unknown_predictions": sum(r["risk_probability"] is None for r in rows),
        "scored": len(scored),
        "known_errors": errors,
        "checks": sum(r["decision"] == "check" for r in rows),
        "known_missed_errors": missed,
        "known_clean_checks": alarms,
        "miss_rate_among_known_errors": _ratio(missed, errors),
        "check_rate_among_known_clean": _ratio(alarms, len(known) - errors),
        "missed_errors_per_row_bounds": [
            missed / len(rows),
            (missed + missing_skips) / len(rows),
        ],
        "brier": _ratio(
            sum((r["risk_probability"] - r["terminal_error"]) ** 2 for r in scored),
            len(scored),
        ),
        "ece": _ratio(
            sum(
                b["known_labels"] * abs(b["mean_risk_known"] - b["error_rate_known"])
                for b in reliability
                if b["known_labels"]
            ),
            len(scored),
        ),
        "reliability": reliability,
    }


def _information(rows):
    cells = defaultdict(list)
    for row in rows:
        cells[tuple(row["feature_key"])].append(row)
    known = sum(r["terminal_error"] is not None for r in rows)
    errors = sum(r["terminal_error"] is True for r in rows)
    optimistic_correct, mixed, shared = 0, 0, 0
    conditional_counts = []
    for cell in cells.values():
        count = sum(r["terminal_error"] is not None for r in cell)
        wrong = sum(r["terminal_error"] is True for r in cell)
        optimistic_correct += max(wrong, count - wrong)
        mixed += 0 < wrong < count
        if count:
            conditional_counts.append((count, wrong))
        if len({r["source_group"] for r in cell}) > 1:
            shared += len(cell)
    return {
        "feature_cells": len(cells),
        "mixed_label_cells": mixed,
        "singleton_rows": sum(len(cell) == 1 for cell in cells.values()),
        "rows_with_cross_source_feature_support": shared,
        "known_labels": known,
        "unknown_labels": len(rows) - known,
        "empirical_best_constant_accuracy_known": _ratio(
            max(errors, known - errors), known
        ),
        "empirical_cell_oracle_accuracy_known": _ratio(optimistic_correct, known),
        # Conditional risks may differ even when every cell has the same class
        # prediction. This known-label variance is descriptive, not admission.
        "empirical_probability_resolution_known": (
            math.fsum(
                count * (wrong / count - errors / known) ** 2
                for count, wrong in conditional_counts
            )
            / known
            if known
            else None
        ),
        "population_information_or_generalization_established": False,
    }


def analyze_observations(rows, *, bins=(0.0, 0.25, 0.5, 0.75, 1.0)):
    """Describe supplied rows; source names do not prove independence.

    Step ordering is checked within a row. This schema has no trusted global
    clock and cannot establish chronological train/cal/confirm/shift collection.
    A check on a later-clean case is an association, not a causal false rejection.
    Missing-label bounds are logical dataset bounds, never confidence intervals.
    """
    rows, bins = list(islice(rows, 100001)), tuple(islice(bins, 22))
    _validate(rows, bins)
    groups = defaultdict(list)
    for row in rows:
        groups[row["phase"], row["view_kind"]].append(row)
    cohorts = {}
    for (phase, view), group in sorted(groups.items()):
        sources = defaultdict(list)
        for row in group:
            sources[row["source_group"]].append(row)
        per_source = {
            source: _metrics(values, bins) for source, values in sorted(sources.items())
        }
        brier = [m["brier"] for m in per_source.values() if m["brier"] is not None]
        cohorts[f"{phase}/{view}"] = {
            "model_sha256": group[0]["model_sha256"],
            "input_schema_sha256": group[0]["input_schema_sha256"],
            "source_clusters": len(sources),
            "task_weighted": _metrics(group, bins),
            "equal_source_mean_brier": _ratio(sum(brier), len(brier)),
            "sources_with_scored_labels": len(brier),
            "by_source": per_source,
            "information": _information(group),
        }
    drift = {}
    for phase in ("confirm", "shift"):
        for view in ("ack", "readback"):
            current = cohorts.get(f"{phase}/{view}")
            if current is None:
                continue
            reference = cohorts.get(f"cal/{view}")
            reasons = []
            if reference is None:
                reasons.append("no_calibration_cohort")
            else:
                for name in ("model_sha256", "input_schema_sha256"):
                    if reference[name] != current[name]:
                        reasons.append(name + "_changed")
            old = reference["task_weighted"] if reference is not None else {}
            new = current["task_weighted"]
            if reference is not None and (
                old["unknown_labels"] or old["unknown_predictions"]
            ):
                reasons.append("calibration_observations_incomplete")
            if new["unknown_labels"] or new["unknown_predictions"]:
                reasons.append("current_observations_incomplete")
            comparison_ready = not reasons
            variation = None
            if (
                reference is not None
                and reference["input_schema_sha256"] == current["input_schema_sha256"]
            ):
                counts = [
                    Counter(tuple(r["feature_key"]) for r in groups[p, view])
                    for p in ("cal", phase)
                ]
                nold, nnew = sum(counts[0].values()), sum(counts[1].values())
                variation = (
                    sum(
                        abs(counts[0][key] / nold - counts[1][key] / nnew)
                        for key in counts[0].keys() | counts[1].keys()
                    )
                    / 2
                )
            drift[f"{phase}/{view}"] = {
                "calibration_reuse_blocked": bool(reasons),
                "recalibration_required": True if reasons else None,
                "reuse_gate_scope": "model_input_identity_and_observation_completeness",
                "statistical_drift_decision": "NOT_PERFORMED",
                "reasons": reasons,
                "comparison_scope_unchanged": reference is not None
                and all(
                    reference[name] == current[name]
                    for name in ("model_sha256", "input_schema_sha256")
                ),
                "brier_change": (
                    new["brier"] - old["brier"]
                    if comparison_ready
                    and new["brier"] is not None
                    and old["brier"] is not None
                    else None
                ),
                "ece_change": (
                    new["ece"] - old["ece"]
                    if comparison_ready
                    and new["ece"] is not None
                    and old["ece"] is not None
                    else None
                ),
                "empirical_feature_total_variation": variation,
                "unknown_labels": new["unknown_labels"],
                "unknown_predictions": new["unknown_predictions"],
                "calibration_validity_established": False,
            }
    return {
        "schema": "hepta.verify.observation-diagnostics.v1",
        "rows": len(rows),
        "frozen_bins": list(bins),
        "bin_intervals": "left_closed_right_open_except_final",
        "cohorts": cohorts,
        "drift": drift,
        "roster_completeness_established": False,
        "phase_time_order_verified": False,
        "source_independence_established": False,
        "causal_false_rejection_rate": None,
        "scientific_admission": "HOLD",
        "production_authority": "NONE",
    }
