"""Legacy-shaped semantic calibration predicates and separate commit risk."""

import math

import numpy as np
from scipy.stats import beta

from .selective_protocol import SPEC


def confidence(probability):
    q = 1 << 24
    pq = int(math.floor(float(probability) * q + .5))
    return 1_000_000 - (q - pq) * 1_000_000 // q


def ece(cp, labels):
    bins = np.minimum(cp // 100000, 9)
    return sum(abs(float(labels[bins == i].sum()) - float(cp[bins == i].sum()) / 1e6)
               for i in range(10)) / len(labels)


def final_choice(probability, category):
    utility = SPEC["final_utility"]
    moment = (probability * math.exp(-utility["gamma"] * (utility["correct_commit"] - utility["commit_cost"]))
        + (1 - probability) * math.exp(-utility["gamma"] * (utility["incorrect_commit"] - utility["commit_cost"])))
    return category == "selected_by_public_head" and moment < 1.0, moment


def summarize(rows):
    y = np.asarray([r["strict_success"] for r in rows], dtype=int)
    cp = np.asarray([r["confidence_ppm"] for r in rows], dtype=np.int64)
    ood = np.asarray([r["declared_ood"] for r in rows], dtype=bool)
    legacy = (cp >= 750000) & ((1_000_000 - cp) <= 500000)
    accepted = np.asarray([r["commit"] for r in rows], dtype=bool)
    ood_n, id_n = int(ood.sum()), int((~ood).sum())
    false_ood = int(legacy[ood].sum())
    upper = 1 - .05 ** (1 / ood_n) if false_ood == 0 else None
    wrong = int(np.sum(accepted & ~ood & (y == 0)))
    result = {"n": len(rows), "id_n": id_n, "ood_n": ood_n,
        "ece_full": float(ece(cp, y)), "ece_id": float(ece(cp[~ood], y[~ood])),
        "legacy_id_coverage": float(legacy[~ood].mean()), "legacy_ood_false_acceptances": false_ood,
        "legacy_ood_far": false_ood / ood_n, "legacy_ood_one_sided_95_upper": upper,
        "selective_id_coverage": float(accepted[~ood].mean()), "selective_ood_accepted": int(accepted[ood].sum()),
        "incorrect_semantic_commits_id": wrong, "incorrect_semantic_commit_per_id_case": wrong / id_n,
        "incorrect_semantic_commit_per_id_one_sided_95_upper": float(beta.ppf(.95, wrong + 1, id_n - wrong)) if wrong < id_n else 1.0,
        "error_among_selective_id_commits": float(np.mean(y[accepted & ~ood] == 0)) if (accepted & ~ood).any() else None,
        "actual_candidate_strict_success_id": float(y[~ood].mean()),
        "probability_category_counts": {g: sum(r["category"] == g for r in rows) for g in SPEC["categories"]},
        "native_production_qualification": False}
    result["legacy_shaped_gates"] = {"ece": max(result["ece_full"], result["ece_id"]) <= .03,
        "ood_far": result["legacy_ood_far"] <= .004999,
        "ood_upper": upper is not None and upper <= .004999,
        "id_nonvacuity": result["legacy_id_coverage"] >= .25}
    result["additional_selective_gates"] = {"id_coverage": result["selective_id_coverage"] >= .25,
        "incorrect_commit_rate": result["incorrect_semantic_commit_per_id_case"] <= .004999}
    result["all_bounded_gates_passed"] = all(result["legacy_shaped_gates"].values()) and all(result["additional_selective_gates"].values())
    return result
