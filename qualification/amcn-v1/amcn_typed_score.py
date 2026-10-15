"""Independent label-opening scorer for original, sealed typed-Cell Head predictions.

Does not train, select a Cell, authorize a graph, infer a Reader answer or
claim an independent real future window from a retrospective partition.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite

from amcn_core import digest, is_sha, require, shadow_disposition
from amcn_learning import FeatureMatrix
from amcn_typed_budget import ARMS, HELDOUT, PROFILE, type_inventory_digest


def score_typed_budget(matrix, type_by_row, predictions, labels, *,
                       pinned_type_sha256, pinned_predictions_sha256):
    """Score every sealed non-TRAIN row, including misses/failures as refusals.

    The source/feature type manifest and prediction digest must be pinned before
    this scorer opens non-TRAIN labels. They are integrity checks, not signatures.
    """
    require(isinstance(matrix, FeatureMatrix), "frozen features required")
    require(is_sha(pinned_type_sha256)
            and pinned_type_sha256 == type_inventory_digest(matrix, type_by_row),
            "type inventory mutated before scoring")
    require(is_sha(pinned_predictions_sha256) and isinstance(predictions, list)
            and digest(predictions) == pinned_predictions_sha256,
            "original predictions not sealed")
    eligible = {r.row_id: r for r in matrix.rows if r.split in HELDOUT}
    require(eligible and isinstance(labels, dict) and set(labels) == set(eligible)
            and all(type(x) is int and x in (0, 1) for x in labels.values()),
            "label set contains TRAIN, omits failures or has invalid targets")
    require(len(predictions) == len(eligible), "partial prediction census")
    outcomes = defaultdict(list)
    paired = defaultdict(list)
    seen = set()
    for pred in predictions:
        require(isinstance(pred, dict) and set(pred) ==
                {"row_id", "family", "split", "input_sha256", "memory_type", "probabilities"},
                "invalid original prediction envelope")
        row = eligible.get(pred["row_id"])
        require(row is not None and row.row_id not in seen, "unknown/duplicate case")
        seen.add(row.row_id)
        require((row.family, row.split, row.input_sha256, type_by_row[row.row_id]) ==
                (pred["family"], pred["split"], pred["input_sha256"], pred["memory_type"]),
                "source, split or typed route changed")
        probs = pred["probabilities"]
        require(isinstance(probs, dict) and set(probs) == set(ARMS),
                "missing independent arm")
        y = labels[row.row_id]
        for arm in ARMS:
            p = probs[arm]
            require(type(p) in (float, int) and isfinite(p) and 0 <= p <= 1,
                    "invalid original probability")
            correct = int((p >= 0.5) == bool(y))
            outcomes[(row.split, arm)].append((correct, (p - y)**2))
        if row.split in ("future_a", "future_b"):
            t = int((probs["typed_equal_budget"] >= 0.5) == bool(y))
            u = int((probs["untyped_equal_budget"] >= 0.5) == bool(y))
            paired[(row.split, row.family)].append(t - u)
    require(seen == set(eligible), "missing sealed cases")
    summaries = []
    for (split, arm), rows in sorted(outcomes.items()):
        summaries.append({"split": split, "arm": arm, "n": len(rows),
                          "accuracy": sum(c for c, _ in rows) / len(rows),
                          "brier": sum(b for _, b in rows) / len(rows)})
    family_outcome = {"win": 0, "loss": 0, "tie": 0}
    for differences in paired.values():
        mean = sum(differences) / len(differences)
        family_outcome["win" if mean > 0 else "loss" if mean < 0 else "tie"] += 1
    return shadow_disposition(profile=PROFILE + ".heldout-score",
                              features_sha256=matrix.identity,
                              type_inventory_sha256=pinned_type_sha256,
                              original_predictions_sha256=pinned_predictions_sha256,
                              complete_case_count=len(eligible),
                              family_pairs=len(paired), family_wins=family_outcome,
                              descriptive_scores=summaries,
                              effective_independent_sample_count=None,
                              future_calendar_observation_verified=False,
                              human_evidence_sufficiency_verified=False,
                              strong_hybrid_rag_superiority_proven=False,
                              learning_efficiency_superiority_proven=False)
