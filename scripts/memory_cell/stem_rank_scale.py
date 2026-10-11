"""Label-free counterfactual ranking geometry, not a deployed scaling policy.

Only the direction of a learned score residual is inspected. This diagnostic
does not use task answers, tune a temperature, certify evidence or change top-1.
"""

import math


def minimum_residual_flip_scale(frozen, learned, candidate_ids):
    """Infimum of nonnegative residual scales which could change frozen top-1.

    For baseline winner w, candidate j gains relative to w by
    (learned[j]-frozen[j])-(learned[w]-frozen[w]). A nonpositive gain
    cannot overturn that winner regardless of scalar amplification.
    At the reported equality boundary the existing lexical tie-break
    can still select w: this is an *infimum*, not a prescription.
    """
    if (
        not isinstance(frozen, (list, tuple))
        or not isinstance(learned, (list, tuple))
        or not isinstance(candidate_ids, (list, tuple))
        or len(candidate_ids) > 64
        or len(frozen) != len(candidate_ids)
        or len(learned) != len(candidate_ids)
        or any(not isinstance(v, str) or not v for v in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
        or any(
            type(v) not in (int, float) or not math.isfinite(v)
            for v in (*frozen, *learned)
        )
    ):
        raise ValueError("finite same-candidate geometry required")
    if len(candidate_ids) < 2:
        return None
    winner = min(
        range(len(candidate_ids)),
        key=lambda i: (-frozen[i], candidate_ids[i]),
    )
    baseline_residual = learned[winner] - frozen[winner]
    if not math.isfinite(baseline_residual):
        raise ValueError("overflowing residual")
    thresholds = []
    for i in range(len(candidate_ids)):
        if i == winner:
            continue
        gain = learned[i] - frozen[i] - baseline_residual
        if not math.isfinite(gain):
            raise ValueError("overflowing candidate relative gain")
        if gain <= 0:
            continue
        margin = frozen[winner] - frozen[i]
        boundary = margin / gain
        if not math.isfinite(boundary) or boundary < 0:
            raise ValueError("invalid positive-scaling boundary")
        thresholds.append(boundary)
    return min(thresholds) if thresholds else None
