"""Post-seal split/System2 evaluation; descriptive public tasks, not NDU authority.

Never supplies held-out labels to a controller. Paired outcomes retain all cases,
resource ceilings are not called equal compute, and a missing arm is an error.
"""
from __future__ import annotations

import math
from pathlib import Path

from experiments.shared_stem_cell.wire import InputError, decode

SPLIT_ARMS = {"parent_no_change", "parent_continued", "inherited_split", "larger_unsplit"}
SYSTEM2_ARMS = {"no_recurrence", "fixed_recurrence", "adaptive", "adaptive_ndu_linear"}


def probability_rows(values, count, classes):
    if not isinstance(values, list) or len(values) != count:
        raise InputError("complete prediction rows required")
    for row in values:
        if (not isinstance(row, list) or len(row) != classes
                or any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1 for x in row)
                or abs(sum(row) - 1) > 1e-5):
            raise InputError("exact finite class probabilities required")
    return values


def summarize(predictions, targets, groups, *, classes, control=None):
    count = len(targets)
    if (type(classes) is not int or not 2 <= classes <= 256 or not count
            or len(groups) != count or not predictions
            or any(type(y) is not int or not 0 <= y < classes for y in targets)
            or any(not isinstance(g, str) or not g for g in groups)):
        raise InputError("bounded score identities/targets required")
    if control is not None and control not in predictions:
        raise InputError("comparison control missing")
    correct, scores = {}, {}
    for arm, raw in predictions.items():
        rows = probability_rows(raw, count, classes)
        correct[arm] = [max(range(classes), key=row.__getitem__) == y for row, y in zip(rows, targets)]
        scores[arm] = {"cases": count, "correct": sum(correct[arm]),
            "accuracy": sum(correct[arm]) / count,
            "brier": sum(sum((p - int(j == y))**2 for j, p in enumerate(row))
                         for row, y in zip(rows, targets)) / count}
    paired = {}
    if control is not None:
        baseline = correct[control]
        for arm, actual in correct.items():
            delta = [int(a) - int(b) for a, b in zip(actual, baseline)]
            group_ids = sorted(set(groups))
            group_delta = {g: sum(d for d, group in zip(delta, groups) if group == g)
                           / sum(group == g for group in groups) for g in group_ids}
            paired[arm] = {"control": control, "gains": sum(d == 1 for d in delta),
                "losses": sum(d == -1 for d in delta), "ties": sum(d == 0 for d in delta),
                "accuracy_delta": sum(delta) / count, "declared_groups": len(group_ids),
                "group_mean_delta": sum(group_delta.values()) / len(group_ids),
                "independent_group_count": None, "confidence_interval": None}
    return {"scores": scores, "paired": paired, "independent_evaluation": False,
            "production_accepted": False}


def evaluate_controls(path: Path, expected, labels, cases, *, classes):
    from experiments.shared_stem_cell.execution import bound_file

    controls = decode(bound_file(path, expected, 64 * 1024**2))
    if not isinstance(controls, dict):
        raise InputError("controls must be a mapping")
    if not controls:
        return {"status": "not_requested", "production_accepted": False}
    if not isinstance(controls, dict) or not {"split", "system2", "holdout_case_ids"} <= set(controls):
        raise InputError("complete controls required")
    available = {c.case_id: c for c in cases if c.split == "holdout"}
    ids = controls["holdout_case_ids"]
    if (not isinstance(ids, list) or len(ids) != len(set(ids)) or set(ids) != set(available)):
        raise InputError("control case coverage drift")
    targets, groups = [labels[i] for i in ids], [available[i].group for i in ids]
    result = {}
    for name, required, reference in (("split", SPLIT_ARMS, "parent_continued"),
                                       ("system2", SYSTEM2_ARMS, "fixed_recurrence")):
        value = controls[name]
        arms = set(value["predictions"])
        if not required <= arms or arms - required - ({"more_data"} if name == "split" else set()):
            raise InputError("control arm set drift")
        if set(value["costs"]) != arms:
            raise InputError("control costs missing")
        result[name] = summarize(value["predictions"], targets, groups,
                                 classes=classes, control=reference)
        if name == "system2":
            usage = {}
            for arm, cost in value["costs"].items():
                depths = cost["depths"]
                if (not isinstance(depths, list) or len(depths) != len(ids)
                        or any(type(n) is not int or not 1 <= n <= 16 for n in depths)
                        or type(cost["cell_transitions"]) is not int
                        or sum(depths) != cost["cell_transitions"]):
                    raise InputError("System2 work trace drift")
                usage[arm] = sum(depths)
            fixed = value["costs"]["fixed_recurrence"]["depths"]
            if len(set(fixed)) != 1 or any(n != 1 for n in value["costs"]["no_recurrence"]["depths"]):
                raise InputError("reference depth drift")
            if any(n > fixed[0] for cost in value["costs"].values() for n in cost["depths"]):
                raise InputError("adaptive depth exceeds fixed ceiling")
            result[name]["cell_transitions"] = usage
            result[name]["matched_compute"] = False
            result[name]["general_fbsde_gain"] = None
    result.update(prediction_sha256=expected, independent_future_evidence=False,
                  production_accepted=False)
    return result
