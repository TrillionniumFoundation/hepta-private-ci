"""Source-pinned, label-free residual-amplification opportunity audit.

For an already completed native 576-attempt STRICT-as-of experiment, inspect
whether each real Head residual could mathematically overturn a frozen top-1.
This is NOT a train-selected policy, answer benefit, semantic citation, or
production authorization. Labels are deliberately never opened.
"""

from collections import defaultdict
import argparse
import json
import math
from pathlib import Path
import statistics

SOURCE = "48118e891a54c0296b182dc4b88d721b5ab4cf5a"
TREE = "4891f100ce520a997e4356c00545bc670d6cbc2b"
SHA256 = "d2147964d4b916a01bfa0051dec3a3e9aaedb5b2864625c5f2a25db0c44f20e0"
GRID = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def audit_rank_opportunity(plan, predictions, experiment):
    """No native support targets or Reader answers are examined by this audit."""
    questions = plan["questions"]
    _require(
        plan["source_commit"] == SOURCE
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1"
        and tuple(plan["arms"]) == ARMS
        and tuple(plan["curriculum_attempted_examples"]) == STAGES
        and set(questions) == {"train", *PHASES}
        and len(questions["train"]) == 48
        and all(len(questions[p]) == 8 for p in PHASES)
        and len({q for values in questions.values() for q in values}) == 80,
        "registered strict-as-of model/question/curriculum drift",
    )
    expected = {
        (stage, phase, q, arm)
        for stage in STAGES
        for phase in PHASES
        for q in questions[phase]
        for arm in ARMS
    }
    observed = {}
    for row in predictions:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        _require(
            key in expected and key not in observed,
            "unknown or duplicate original policy row",
        )
        geo = row.get("selection_geometry")
        _require(
            row["status"] == "succeeded"
            and isinstance(geo, dict)
            and geo.get("schema") == "hepta.stem-selection-geometry.v2"
            and geo.get("selected_index") == row.get("selected")
            and geo.get("has_ranking_competition") is True
            and type(geo.get("candidate_count")) is int
            and 2 <= geo["candidate_count"] <= 64
            and isinstance(row.get("pool_digest"), str)
            and bool(row["pool_digest"]),
            "missing true selected candidate or sealed ranking receipt",
        )
        observed[key] = row
    _require(
        set(observed) == expected and len(observed) == 576,
        "incomplete original 576-attempt matrix",
    )
    published = experiment["selection_geometry"]
    output = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS[1:]:
                counts = defaultdict(int)
                bounds, margins = [], []
                for q in questions[phase]:
                    baseline = observed[stage, phase, q, "frozen_rerank"]
                    row = observed[stage, phase, q, arm]
                    frozen = baseline["selection_geometry"]
                    geom = row["selection_geometry"]
                    _require(
                        baseline["pool_digest"] == row["pool_digest"]
                        and baseline["cell"] == row["cell"]
                        and baseline["family"] == row["family"]
                        and frozen["baseline_top_id"] == geom["baseline_top_id"]
                        and frozen["selected_index"] == baseline["selected"]
                        and geom["candidate_count"] == frozen["candidate_count"]
                        and type(geom["changed_selected_candidate"]) is bool
                        and geom["changed_selected_candidate"]
                        == (row["selected"] != baseline["selected"])
                        and geom["residual_scaling_is_not_a_validated_policy"] is True
                        and geom["label_free"] is True,
                        "unmatched frozen source pool or invalid shadow-geometry claim",
                    )
                    if row["selected"] != baseline["selected"]:
                        counts["actual_top1_changed"] += 1
                    limit = geom["joint_flip_scale_infimum"]
                    if limit is None:
                        counts["cannot_reverse_frozen_by_nonnegative_scale"] += 1
                    else:
                        _require(
                            type(limit) in (int, float)
                            and math.isfinite(limit)
                            and limit >= 0,
                            "nonfinite, invalid or negative flip threshold",
                        )
                        bounds.append(limit)
                        for alpha in GRID:
                            # Infimum can be a no-flip tie boundary, so keep
                            # strict guaranteed-candidate/possible upper counts.
                            if limit < alpha:
                                counts[f"strictly_below_{alpha:g}"] += 1
                            if limit <= alpha:
                                counts[f"at_or_below_{alpha:g}"] += 1
                    frozen_gap = geom["frozen_top1_gap"]
                    _require(
                        type(frozen_gap) in (int, float)
                        and math.isfinite(frozen_gap)
                        and frozen_gap >= 0,
                        "invalid frozen top-1 score gap",
                    )
                    margins.append(frozen_gap)
                key = f"{stage}/{phase}/{arm}"
                archived = published[key]
                _require(
                    len(margins) == 8
                    and archived["observed_pre_reader_decisions"] == 8
                    and archived["changed_top1_count"] == counts["actual_top1_changed"]
                    and archived["joint_direction_can_flip_count"] == len(bounds)
                    and archived["joint_direction_cannot_flip_count"]
                    == counts["cannot_reverse_frozen_by_nonnegative_scale"],
                    "counterfactual receipt does not match source-pinned journal",
                )
                output[key] = dict(
                    original_planned_questions=8,
                    actual_source_selection_changes=counts["actual_top1_changed"],
                    possible_flip_directions=len(bounds),
                    wrong_or_uniform_residual_directions=counts[
                        "cannot_reverse_frozen_by_nonnegative_scale"
                    ],
                    frozen_top1_gap_median=statistics.median(margins),
                    median_residual_scale_infimum=(
                        statistics.median(bounds) if bounds else None
                    ),
                    worst_observed_infimum=max(bounds) if bounds else None,
                    strict_flip_potential_within_grid={
                        str(alpha): counts[f"strictly_below_{alpha:g}"]
                        for alpha in GRID
                    },
                    possible_flip_at_or_below_grid={
                        str(alpha): counts[f"at_or_below_{alpha:g}"] for alpha in GRID
                    },
                    **{
                        "no_source_truth_or_task_answer_read": True,
                        "same_fixed_reader_original_policy_unchanged": True,
                        "threshold_is_only_an_infimum": True,
                        "winner_could_be_wrong_even_after_flip": True,
                    },
                )
    return dict(
        schema="hepta.stem-archived-residual-scale-opportunity.v1",
        generating_source=SOURCE,
        generating_tree=TREE,
        actual_original_policy_attempts=576,
        original_policy_source_digest_not_reinterpreted=True,
        fixed_grid=GRID,
        no_label_training_or_selection_or_reader_calls=True,
        retrospective_thresholds_only_not_train_selected_shadow_scale=True,
        no_native_support_labels_or_answers_read=True,
        independent_task_superiority_established=False,
        semantic_citation_precision=None,
        production_accepted=False,
        groups=output,
    )


def audit_zip(path):
    # Reuse the independently tested original ZIP byte/manifest validator.
    from stem_audit_archive import PinnedArchive

    archive = PinnedArchive(Path(path), SHA256)
    try:
        _require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "generating source/tree SHA differs from externally pinned artifact",
        )
        report = audit_rank_opportunity(
            archive.json("comparison/preregistered.json"),
            archive.jsonl("comparison/policy-predictions.jsonl"),
            archive.json("comparison/report.json"),
        )
        report["zip_sha256"] = archive.sha256
        report["verified_manifest_entries"] = archive.manifest_entries
        return report
    finally:
        archive.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_zip(args.artifact)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            dict(
                schema=report["schema"],
                groups=len(report["groups"]),
                production_accepted=False,
            )
        )
    )


if __name__ == "__main__":
    main()
