"""Immutable label-free audit: is learned rank change in a useful direction?

Read the SHA-pinned 576-attempt STRICT as-of six-arm native artifact. Count
whether learned residuals can ever change the frozen winner, vs merely need
greater relative magnitude. An infimum is not a calibrated new serving policy.
No answer labels, citations, Reader, optimizer or gradient execution occurs.
"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import statistics

from stem_audit_archive import PinnedArchive, require

SOURCE = "cb9e98365b5f46e00fb2693f548a7215b1ed1145"
TREE = "022c9aa8abc095c91ef744644329aaed12564859"
ZIP_SHA256 = "be3393f448993451c7860e8867e28a79f5fb7f95d5773f79ed55b30d12a84776"
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
CELLS = ("general", "temporal")
FIELDS = (
    "observed_pre_reader_decisions",
    "competing_pools",
    "changed_top1_count",
    "joint_direction_can_flip_count",
    "joint_direction_cannot_flip_count",
    "joint_requires_scale_above_one_count",
)


def _scale(value):
    require(
        value is None
        or type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0,
        "invalid actual joint residual flip threshold",
    )
    return value


def audit_rank_direction(plan, predictions, persisted_geometry):
    """Only originally executed policy/geometry receipts; zero benchmark targets."""
    cohorts = plan["questions"]
    registered = [qid for phase in ("train", *PHASES) for qid in cohorts[phase]]
    require(
        tuple(plan["arms"]) == ARMS
        and tuple(plan["curriculum_attempted_examples"]) == STAGES
        and tuple(plan["cells"]) == CELLS
        and len(cohorts["train"]) == 48
        and all(len(cohorts[phase]) == 8 for phase in PHASES)
        and len(registered) == len(set(registered)) == 80
        and set(plan["routes"]) == set(registered)
        and set(plan["question_families"]) == set(registered)
        and plan["source_visibility_policy"]
        == "strict-as-of-before-index-and-every-Encoder-v1",
        "not the original registered 80-question strict as-of cohort",
    )
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in cohorts[phase]
        for arm in ARMS
    }
    indexed, grouped = {}, defaultdict(list)
    for row in predictions:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        require(
            key in expected and key not in indexed, "unregistered or duplicated policy"
        )
        require(
            row["status"] == "succeeded"
            and row["cell"] == plan["routes"][row["question_id"]]
            and row["family"] == plan["question_families"][row["question_id"]],
            "failed policy or reassigned original question/source family",
        )
        g = row.get("selection_geometry")
        require(
            isinstance(g, dict)
            and g.get("schema") == "hepta.stem-selection-geometry.v2"
            and type(g.get("candidate_count")) is int
            and 2 <= g["candidate_count"] <= 64
            and g.get("has_ranking_competition") is True
            and g.get("forced_top1") is False
            and g.get("empty_pool") is False
            and g.get("label_free") is True
            and g.get("evidence_entailment_evaluated") is False
            and g.get("no_answer_policy_calibrated") is False
            and g.get("residual_scaling_is_not_a_validated_policy") is True
            and isinstance(g.get("raw_scores_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", g["raw_scores_sha256"]) is not None
            and type(g.get("selected_index")) is int
            and row.get("selected") == g["selected_index"]
            and bool(g.get("baseline_top_id"))
            and bool(g.get("learned_top_id"))
            and bool(g.get("encoder_only_top_id")),
            "unbound or unlabelled saved actual rank geometry",
        )
        adapted = row["arm"] in ("lineage_lora_gated", "independent_lora_gated")
        require(
            g.get("encoder_adapted") is adapted
            and g.get("changed_selected_candidate")
            is (g["baseline_top_id"] != g["learned_top_id"])
            and g.get("encoder_only_changed_selected_candidate")
            is (g["baseline_top_id"] != g["encoder_only_top_id"])
            and g.get("head_changed_selected_candidate")
            is (g["encoder_only_top_id"] != g["learned_top_id"]),
            "Head/Encoder flip attribution contradicts pinned winner identities",
        )
        if not adapted:
            require(
                g["encoder_only_top_id"] == g["baseline_top_id"],
                "unadapted Encoder cannot change its frozen ranking",
            )
        joint = _scale(g.get("joint_flip_scale_infimum"))
        encoder = _scale(g.get("encoder_only_flip_scale_infimum"))
        head = _scale(g.get("head_conditional_flip_scale_infimum"))
        if row["arm"] == "frozen_rerank":
            require(
                joint is None
                and encoder is None
                and head is None
                and g["baseline_top_id"] == g["learned_top_id"],
                "nonlearning frozen control acquired a residual flip",
            )
        if joint is None:
            require(
                not g["changed_selected_candidate"],
                "observed changed selection lacks possible joint flip",
            )
        else:
            require(
                joint >= 0
                and (
                    joint <= 1 + 1e-9
                    if g["changed_selected_candidate"]
                    else joint >= 1 - 1e-9
                ),
                "actual top-1 change disagrees with residual scaling infimum",
            )
        require(
            type(g.get("gap_exceeds_twice_max_residual")) is bool
            and type(g.get("max_abs_score_delta")) in (int, float)
            and math.isfinite(g["max_abs_score_delta"])
            and g["max_abs_score_delta"] >= 0,
            "nonfinite or counterfeit original margin/delta",
        )
        indexed[key] = row
        grouped[(row["stage"], row["phase"], row["arm"])].append(g)
    require(
        set(indexed) == expected and len(indexed) == 576,
        "incomplete original 576 policy-choice record set",
    )
    require(
        isinstance(persisted_geometry, dict) and len(persisted_geometry) == 72,
        "incomplete original 72 score-geometry checkpoint groups",
    )

    by_group = {}
    for (stage, phase, arm), rows in sorted(grouped.items()):
        key = f"{stage}/{phase}/{arm}"
        receipt = persisted_geometry.get(key)
        require(isinstance(receipt, dict), "missing original geometry summary")
        computed = dict(
            observed_pre_reader_decisions=len(rows),
            competing_pools=len(rows),
            changed_top1_count=sum(x["changed_selected_candidate"] for x in rows),
            joint_direction_can_flip_count=sum(
                x["joint_flip_scale_infimum"] is not None for x in rows
            ),
            joint_direction_cannot_flip_count=sum(
                x["joint_flip_scale_infimum"] is None for x in rows
            ),
            joint_requires_scale_above_one_count=sum(
                x["joint_flip_scale_infimum"] is not None
                and x["joint_flip_scale_infimum"] > 1
                for x in rows
            ),
        )
        require(
            all(receipt.get(k) == computed[k] for k in FIELDS),
            "rank-direction totals differ from original model-run report",
        )
        requires = sorted(
            x["joint_flip_scale_infimum"]
            for x in rows
            if x["joint_flip_scale_infimum"] is not None
            and x["joint_flip_scale_infimum"] > 1
        )
        by_group[key] = dict(
            planned=8,
            observed=len(rows),
            natural_rank_flips=computed["changed_top1_count"],
            directional_flip_possible=computed["joint_direction_can_flip_count"],
            direction_cannot_flip=computed["joint_direction_cannot_flip_count"],
            direction_correct_but_scale_above_one=computed[
                "joint_requires_scale_above_one_count"
            ],
            min_scale_above_one=min(requires) if requires else None,
            median_scale_above_one=statistics.median(requires) if requires else None,
            max_scale_above_one=max(requires) if requires else None,
            encoder_only_rank_flips=sum(
                x["encoder_only_changed_selected_candidate"] for x in rows
            ),
            head_conditional_rank_flips=sum(
                x["head_changed_selected_candidate"] for x in rows
            ),
            candidate_count_min=min(x["candidate_count"] for x in rows),
            candidate_count_max=max(x["candidate_count"] for x in rows),
            frozen_margin_stronger_than_twice_joint_delta=sum(
                x["gap_exceeds_twice_max_residual"] for x in rows
            ),
            no_hyperparameter_selection_performed=True,
        )
    final_heldout = {}
    for arm in ARMS[1:]:
        rows = [by_group[f"48/{phase}/{arm}"] for phase in ("test", "transfer")]
        final_heldout[arm] = dict(
            independent_question_count=16,
            native_source_family_count=len(
                {
                    plan["question_families"][qid]
                    for phase in ("test", "transfer")
                    for qid in cohorts[phase]
                }
            ),
            natural_rank_flips=sum(x["natural_rank_flips"] for x in rows),
            direction_cannot_flip=sum(x["direction_cannot_flip"] for x in rows),
            direction_correct_but_scale_above_one=sum(
                x["direction_correct_but_scale_above_one"] for x in rows
            ),
            higher_scale_not_a_permitted_trained_policy=True,
            real_native_support_gain_evaluated_here=False,
        )
    return dict(
        schema="hepta.stem-strict-pinned-rank-direction.v1",
        generator_source=SOURCE,
        generator_tree=TREE,
        registered_unique_questions=80,
        policy_attempts=576,
        model_or_reader_executions=0,
        repeated_test_checkpoint_observations_not_independent=True,
        by_stage_phase_arm=by_group,
        final_test_transfer=final_heldout,
        frozen_to_head_counterfactual_scalar_is_not_a_new_policy=True,
        ground_truth_or_citation_entailment_read=False,
        independent_semantic_precision=None,
        production_accepted=False,
    )


def audit_pinned_strict(path):
    archive = PinnedArchive(Path(path), ZIP_SHA256)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "wrong original strict six-arm generator commit or tree",
        )
        plan = archive.json("comparison/preregistered.json")
        attempts = archive.jsonl("comparison/policy-predictions.jsonl")
        report = archive.json("comparison/report.json")
        result = audit_rank_direction(plan, attempts, report["selection_geometry"])
        result["original_archive_sha256"] = archive.sha256
        result["verified_archive_members"] = archive.manifest_entries
        return result
    finally:
        archive.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit_pinned_strict(args.strict_zip)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
