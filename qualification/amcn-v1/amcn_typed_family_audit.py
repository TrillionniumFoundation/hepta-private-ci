"""Source-family conservative typed-vs-untyped audit over sealed Head predictions.

One independent source family gets one equal-weighted paired observation,
regardless of repeated questions. A family name or synthetic 'future' split
never proves independent issuance or prospective calendar observation.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite, sqrt

from amcn_core import digest, is_sha, require, shadow_disposition
from amcn_learning import FeatureMatrix
from amcn_typed_budget import type_inventory_digest
from amcn_typed_score import score_typed_budget

PROFILE = "hepta.amcn.typed-family-paired.shadow.v1"


def family_paired_audit(matrix, type_by_row, predictions, labels, *,
                        pinned_type_sha256, pinned_predictions_sha256):
    """Return descriptive family-level mean and conservative range, never promotion."""
    require(isinstance(matrix, FeatureMatrix), "immutable features required")
    # Original complete five-arm case and source identity controls are mandatory.
    score = score_typed_budget(
        matrix, type_by_row, predictions, labels,
        pinned_type_sha256=pinned_type_sha256,
        pinned_predictions_sha256=pinned_predictions_sha256)
    require(is_sha(pinned_type_sha256) and
            pinned_type_sha256 == type_inventory_digest(matrix, type_by_row),
            "type manifest drift")
    family_by_split = defaultdict(lambda: defaultdict(list))
    types_by_group = defaultdict(set)
    for row in matrix.rows:
        if row.split in ("future_a", "future_b"):
            types_by_group[row.family].add(row.split)
    require(all(len(partitions) == 1 for partitions in types_by_group.values()),
            "family reused across future panels")
    lookup = {r.row_id: r for r in matrix.rows}
    for row in predictions:
        original = lookup[row["row_id"]]
        if original.split not in ("future_a", "future_b"):
            continue
        p = row["probabilities"]
        y = labels[original.row_id]
        t = int((p["typed_equal_budget"] >= 0.5) == bool(y))
        u = int((p["untyped_equal_budget"] >= 0.5) == bool(y))
        family_by_split[original.split][original.family].append(t - u)
    require(all(family_by_split[s] for s in ("future_a", "future_b")),
            "both frozen future partitions required")
    results = {}
    all_deltas = []
    for split in ("future_a", "future_b"):
        family_values = [sum(v) / len(v) for _, v in
                         sorted(family_by_split[split].items())]
        all_deltas.extend(family_values)
        n = len(family_values)
        mean = sum(family_values) / n
        results[split] = {
            "family_count": n,
            "paired_mean_accuracy_delta": mean,
            "worst_family_delta": min(family_values),
            "best_family_delta": max(family_values),
            "family_wins": sum(x > 0 for x in family_values),
            "family_losses": sum(x < 0 for x in family_values),
            "family_ties": sum(x == 0 for x in family_values)}
    n = len(all_deltas)
    grand_mean = sum(all_deltas) / n
    # Useful as a descriptive standard error ONLY: families are not issuer-
    # authenticated independent samples and the labels are often retrospective.
    variability = (sum((v - grand_mean)**2 for v in all_deltas) /
                   (n - 1)) if n > 1 else None
    stderr = sqrt(variability / n) if variability is not None else None
    require(all(isfinite(x) for x in all_deltas) and isfinite(grand_mean),
            "nonfinite family outcomes")
    return shadow_disposition(
        profile=PROFILE, original_score_sha256=digest(score),
        feature_sha256=matrix.identity, type_inventory_sha256=pinned_type_sha256,
        predictions_sha256=pinned_predictions_sha256,
        family_panel_results=results, descriptive_family_mean_delta=grand_mean,
        descriptive_family_stderr=stderr,
        observed_family_group_count=n,
        independently_verified_family_count=None,
        independently_observed_future_calendar_windows=0,
        task_success_vs_strong_rag=None, reader_sufficiency=None,
        lower_confidence_bound_for_promotion=None,
        typed_superiority_qualified=False)
