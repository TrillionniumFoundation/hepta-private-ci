"""Post-seal per-source-family retention guard for actual Cell consolidation.

Only model-produced, already sealed prediction probabilities and original
dataset labels enter this post-hoc scoring function; never supply these labels
to the fitting/selection Head or use it as a production selection authority.
"""
from __future__ import annotations

import math


class GroupAuditError(ValueError):
    pass


def evaluate(predictions, cases, labels, *, control="bank"):
    if type(predictions) is not dict or control not in predictions:
        raise GroupAuditError("unchanged frozen teacher bank required")
    if not 1 <= len(predictions) <= 32 or not 1 <= len(cases) <= 16384:
        raise GroupAuditError("bounded complete source inventory required")
    if type(labels) is not list or len(labels) != len(cases):
        raise GroupAuditError("complete post-seal original labels required")
    ids, registered_groups, registered_splits = set(), {}, {}
    for case in cases:
        for key in ("case_id", "group", "split", "scope"):
            if not isinstance(getattr(case, key, None), str) or not getattr(case, key):
                raise GroupAuditError("original source identity missing")
        if case.case_id in ids or case.split not in ("holdout", "retention"):
            raise GroupAuditError("only distinct heldout/retention cases allowed")
        ids.add(case.case_id)
        if case.group in registered_splits and registered_splits[case.group] != case.split:
            raise GroupAuditError("source family appears in different test splits")
        registered_groups[case.case_id] = case.group
        registered_splits[case.group] = case.split
    if len({case.scope for case in cases}) != 1:
        raise GroupAuditError("cross-scope evaluation prohibited")
    if any(type(y) is not int or not 0 <= y <= 255 for y in labels):
        raise GroupAuditError("invalid original supervised outcome")
    correctness, groups = {}, {}
    classes = None
    for arm, rows in predictions.items():
        if not isinstance(arm, str) or not arm or not isinstance(rows, list) or len(rows) != len(cases):
            raise GroupAuditError("missing/extra prediction rows")
        actual = []
        for probs, y in zip(rows, labels):
            if not isinstance(probs, list) or not 2 <= len(probs) <= 256:
                raise GroupAuditError("missing class probabilities")
            if classes is None:
                classes = len(probs)
            if (len(probs) != classes or y >= classes
                    or any(type(p) not in (int, float) or not math.isfinite(p)
                           or not 0 <= p <= 1 for p in probs)
                    or abs(math.fsum(probs) - 1) > 1e-5):
                raise GroupAuditError("invalid post-seal normalized probabilities")
            actual.append(int(max(range(classes), key=probs.__getitem__) == y))
        correctness[arm] = actual
    if control not in correctness:
        raise GroupAuditError("unchanged model unavailable")
    summaries = {}
    for arm, found in correctness.items():
        by_source = {}
        for row, case in enumerate(cases):
            group_id = (case.split, registered_groups[case.case_id], case.cell)
            record = by_source.setdefault(group_id, {
                "cases": 0, "model_correct": 0, "bank_correct": 0,
                "paired_gain": 0, "paired_loss": 0
            })
            base, current = correctness[control][row], found[row]
            record["cases"] += 1
            record["model_correct"] += current
            record["bank_correct"] += base
            record["paired_gain"] += int(current > base)
            record["paired_loss"] += int(current < base)
        rows = [{"split": split, "source_group": group, "cell": cell, **numbers}
                for (split, group, cell), numbers in sorted(by_source.items())]
        summaries[arm] = {
            "cases": len(cases), "source_groups_by_cell": len(rows),
            "correct": sum(found), "bank_correct": sum(correctness[control]),
            "paired_gains": sum(x > y for x, y in zip(found, correctness[control])),
            "paired_losses": sum(x < y for x, y in zip(found, correctness[control])),
            "empirical_no_source_group_regression": all(
                entry["model_correct"] >= entry["bank_correct"] for entry in rows
            ),
            "holdout_nonregression": all(
                entry["model_correct"] >= entry["bank_correct"]
                for entry in rows if entry["split"] == "holdout"
            ),
            "retention_nonregression": all(
                entry["model_correct"] >= entry["bank_correct"]
                for entry in rows if entry["split"] == "retention"
            ),
            "source_rows": rows
        }
    return {
        "schema": "hepta.consolidation.group-retention-audit.v1",
        "baseline": control, "scores": summaries,
        "uses_sealed_predictions_only": True,
        "independent_source_families_verified": False,
        "future_task_retention_certified": False,
        "production_accepted": False
    }
