"""Lineage-connected source-family comparison for sealed typed MemoryCell Heads.

A logical family name is not an independent sample.  Families sharing one
source_root, and roots sharing one family, form ONE connected exposure group.
The output is strictly descriptive: neither provenance names nor synthetic
'future' folds attest independent issuers or future calendar observations.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite, sqrt

from amcn_core import digest, is_sha, require, shadow_disposition
from amcn_learning import FeatureMatrix
from amcn_typed_budget import type_inventory_digest
from amcn_typed_score import score_typed_budget

PROFILE = "hepta.amcn.typed-family-paired.shadow.v2"
FUTURES = ("future_a", "future_b")


def _components(rows):
    """Deterministic bipartite source-root/family connected components."""
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    def join(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)

    for row in rows:
        require(isinstance(row.source_root, str) and row.source_root and
                isinstance(row.family, str) and row.family,
                "missing lineage root or family")
        join(("root", row.source_root), ("family", row.family))
    grouped = defaultdict(list)
    for row in rows:
        grouped[find(("root", row.source_root))].append(row)
    return [tuple(sorted(group, key=lambda r: r.row_id))
            for _, group in sorted(grouped.items())]


def family_paired_audit(matrix, type_by_row, predictions, labels, *,
                        pinned_type_sha256, pinned_predictions_sha256):
    """Count connected source components, not just renamed family labels."""
    require(isinstance(matrix, FeatureMatrix), "immutable features required")
    score = score_typed_budget(
        matrix, type_by_row, predictions, labels,
        pinned_type_sha256=pinned_type_sha256,
        pinned_predictions_sha256=pinned_predictions_sha256)
    require(is_sha(pinned_type_sha256) and
            pinned_type_sha256 == type_inventory_digest(matrix, type_by_row),
            "typed inventory drift")
    panels = {s: [r for r in matrix.rows if r.split == s] for s in FUTURES}
    require(all(panels.values()), "both future panels must be complete")
    # If a lineage bridges panels, the same source must not be counted twice.
    for key in ("family", "source_root"):
        seen = {}
        for split in FUTURES:
            for row in panels[split]:
                value = getattr(row, key)
                require(seen.setdefault(value, split) == split,
                        "source-root/family reused across future panels")

    lookup = {r.row_id: r for r in matrix.rows}
    paired = {}
    for original in predictions:
        row = lookup[original["row_id"]]
        if row.split not in FUTURES:
            continue
        probs = original["probabilities"]
        y = labels[row.row_id]
        typed = int((probs["typed_equal_budget"] >= 0.5) == bool(y))
        untyped = int((probs["untyped_equal_budget"] >= 0.5) == bool(y))
        require(row.row_id not in paired, "duplicate paired result")
        paired[row.row_id] = typed - untyped
    require(set(paired) == {r.row_id for s in FUTURES for r in panels[s]},
            "missing source-connected paired result")

    results, deltas, component_manifests = {}, [], []
    for split in FUTURES:
        components = _components(panels[split])
        values = []
        for group in components:
            values.append(sum(paired[r.row_id] for r in group) / len(group))
            component_manifests.append([split, sorted(r.row_id for r in group),
                                        sorted({r.source_root for r in group}),
                                        sorted({r.family for r in group})])
        require(values and all(isfinite(x) and -1 <= x <= 1 for x in values),
                "invalid component accuracy difference")
        deltas.extend(values)
        results[split] = {
            "family_count": len(components),  # legacy output: now components, not names
            "source_component_count": len(components),
            "distinct_family_labels": len({r.family for r in panels[split]}),
            "distinct_source_roots": len({r.source_root for r in panels[split]}),
            "merged_family_aliases": sum(
                len({r.family for r in g}) > 1 for g in components),
            "paired_mean_accuracy_delta": sum(values) / len(values),
            "worst_family_delta": min(values),
            "best_family_delta": max(values),
            "family_wins": sum(v > 0 for v in values),
            "family_losses": sum(v < 0 for v in values),
            "family_ties": sum(v == 0 for v in values),
        }
    n = len(deltas)
    mean = sum(deltas) / n
    # Descriptive only: no IID claim or inferential p-values.
    stderr = sqrt(sum((v - mean)**2 for v in deltas) / (n * (n - 1))) \
        if n > 1 else None
    return shadow_disposition(
        profile=PROFILE, original_score_sha256=digest(score),
        feature_sha256=matrix.identity, type_inventory_sha256=pinned_type_sha256,
        predictions_sha256=pinned_predictions_sha256,
        component_manifest_sha256=digest(sorted(component_manifests)),
        component_rule="bipartite-source-root-family-connected-components-v1",
        family_panel_results=results, descriptive_family_mean_delta=mean,
        descriptive_family_stderr=stderr,
        observed_family_group_count=n,
        observed_source_component_count=n,
        independently_verified_family_count=None,
        independently_observed_future_calendar_windows=0,
        task_success_vs_strong_rag=None, reader_sufficiency=None,
        lower_confidence_bound_for_promotion=None,
        typed_superiority_qualified=False)
