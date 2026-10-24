"""Aggregate truth-looking prefix audit; no deployable policy is produced."""
import math
from statistics import fmean


def summarize(rows):
    if not rows:
        raise ValueError("nonempty paired records required")
    for row in rows:
        for modality in ("audio", "video"):
            values = row[modality + "_mse"]
            if len(values) != 4 or any(type(x) not in (float, int) or
                                      not math.isfinite(x) or x < 0 for x in values):
                raise ValueError("four finite nonnegative prefix losses required")
            size = row[modality + "_scalars"]
            if type(size) is not int or size <= 0:
                raise ValueError("positive scalar count required")
    actions = [(a, v) for a in range(4) for v in range(4)]

    def loss(row, action):
        a, v = action
        return .5 * (row["audio_mse"][a] + row["video_mse"][v])

    def macs(row, action):
        a, v = action
        return 64 * (a * row["audio_scalars"] + v * row["video_scalars"])

    frontiers = []
    for exact in (True, False):
        for budget in range(7):
            eligible = [action for action in actions if
                        (sum(action) == budget if exact else sum(action) <= budget)]
            fixed = min(eligible, key=lambda action:
                        (fmean(loss(row, action) for row in rows), sum(action), action))
            chosen = [min(eligible, key=lambda action:
                          (loss(row, action), sum(action), action)) for row in rows]
            fixed_loss = fmean(loss(row, fixed) for row in rows)
            oracle_loss = fmean(loss(row, action) for row, action in zip(rows, chosen))
            frontiers.append({"budget": budget,
                              "semantics": "exact_calls" if exact else "at_most_calls",
                              "static_prefix": list(fixed), "coverage": 1.0,
                              "static_mean_mse": fixed_loss, "oracle_mean_mse": oracle_loss,
                              "mean_headroom": fmean(loss(row, fixed) - loss(row, action)
                                                     for row, action in zip(rows, chosen)),
                              "static_mean_calls": sum(fixed),
                              "oracle_mean_calls": fmean(sum(action) for action in chosen),
                              "static_matrix_macs": sum(macs(row, fixed) for row in rows),
                              "oracle_matrix_macs": sum(macs(row, action) for row, action in zip(rows, chosen))})
    modalities = {}
    for modality in ("audio", "video"):
        values = [row[modality + "_mse"] for row in rows]
        means = [fmean(v[index] for v in values) for index in range(4)]
        fixed = min(range(4), key=lambda index: (means[index], index))
        optimum = fmean(min(v) for v in values)
        modalities[modality] = {"mean_mse_by_round": means, "best_fixed_round": fixed,
                                "oracle_mean_mse": optimum,
                                "headroom_over_best_fixed": means[fixed] - optimum,
                                "improvement_over_no_refine": means[0] - optimum,
                                "worsening_transitions": [sum(v[i] > v[i-1] for v in values)
                                                          for i in range(1, 4)]}
    return {"clips": len(rows), "coverage": 1.0, "modalities": modalities,
            "frontiers": frontiers, "oracle_is_deployable": False,
            "physical_cost_matched": False, "scientific_efficacy_confirmed": False,
            "eager_audit_calls": 6 * len(rows),
            "eager_matrix_macs": sum(macs(row, (3, 3)) for row in rows)}
