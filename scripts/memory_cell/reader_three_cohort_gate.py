"""Independent, read-only evidence reconciliation across three Qwen interventions.

The two original verifiers enforce their own immutable, externally pinned ZIP
censuses and untouched generated answers. This bridge adds a cross-study parity
check: published LoCoMo questions and publisher-privileged source selection
cannot be misrepresented as new independent families or learned memory.

No language model, benchmark tuning, weights, signing or deployment is invoked.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

SCHEMA = "hepta.memory-cell.reader-three-cohort-research-disposition.v1"
CROSS_SCHEMA = "hepta.memory-cell.cross-population-evidence.v1"
PUBLISHER_SCHEMA = "hepta.locomo.publisher-support-postrun.v1"
CROSS_NAMES = (
    "event_model",
    "event_replay",
    "locomo_public",
    "locomo_retrieval",
    "locomo_targets",
    "locomo_model",
    "locomo_score",
)
PUBLISHER_NAMES = ("publisher_plan", "publisher_model", "publisher_score")


def _rate(value):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("bounded original published F1 required")
    return float(value)


def _no_promotion(cross, publisher):
    flags = cross["qualification"]
    required = (
        flags["frozen_reader_evidence_transfer_proven"] is False
        and flags["calibrated_k_stable"] is False
        and flags["independent_future_source_families"] == 0
        and flags["human_certified_sufficient_contexts"] == 0
        and flags["semantic_citation_precision"] is None
        and flags["parametric_memory_training_qualified"] is False
        and flags["production_accepted"] is False
        and publisher["publisher_source_selection_is_privileged"] is True
        and publisher["new_independently_admitted_source_families"] == 0
        and publisher["independent_semantic_citation_judgement"] is False
        and publisher["parameter_memory_gain_established"] is False
        and publisher["production_accepted"] is False
    )
    if not required:
        raise ValueError("original non-promotion/privilege boundary changed")


def join_verified(cross: dict, publisher: dict) -> dict:
    """Check distinct runs and matching LoCoMo baselines; never pool metrics."""
    if (
        not isinstance(cross, dict)
        or not isinstance(publisher, dict)
        or cross.get("schema") != CROSS_SCHEMA
        or publisher.get("schema") != PUBLISHER_SCHEMA
        or cross.get("reader_identity") != publisher.get("frozen_reader_identity")
        or cross.get("observed_completed_model_calls") != 144
        or publisher.get("original_model_calls") != 16
        or cross["controlled_authored_event"]["original_model_calls"] != 112
        or cross["published_locomo"]["original_model_calls"] != 32
        or cross["published_locomo"]["published_development_questions"] != 16
        or cross["published_locomo"]["source_family_proxies"] != 2
        or publisher.get("matched_public_family_proxies") != 2
        or cross.get("pooled_accuracy") is not None
    ):
        raise ValueError("inconsistent model lineage or distinct source populations")

    _no_promotion(cross, publisher)
    matched = {}
    for name in ("lexical_k4", "lexical_k8"):
        control = cross["published_locomo"]["arms"][name]
        other = publisher["original_matched_f1"][name]
        baseline = _rate(control["mean_diagnostic_token_f1"])
        replayed = _rate(other["baseline_token_f1"])
        privileged = _rate(other["privileged_token_f1"])
        delta = other["descriptive_delta"]
        if (
            not math.isclose(baseline, replayed, rel_tol=0, abs_tol=1e-10)
            or type(delta) not in (int, float)
            or not math.isfinite(delta)
            or not math.isclose(privileged - replayed, delta, rel_tol=0, abs_tol=1e-10)
            or control["successful_model_calls"] != 16
            or any(
                type(other[field]) is not int or not 0 <= other[field] <= 16
                for field in ("paired_wins", "paired_losses", "paired_ties")
            )
            or sum(
                other[field] for field in ("paired_wins", "paired_losses", "paired_ties")
            ) != 16
        ):
            raise ValueError("privileged intervention detached from original LoCoMo reader")
        matched[name] = dict(
            original_mean_token_f1=baseline,
            privileged_mean_token_f1=privileged,
            descriptive_privileged_delta=delta,
            paired_wins=other["paired_wins"],
            paired_losses=other["paired_losses"],
            paired_ties=other["paired_ties"],
            allowed_as_online_retrieval_or_learned_memory=False,
        )
    if not math.isclose(
        matched["lexical_k4"]["privileged_mean_token_f1"],
        matched["lexical_k8"]["privileged_mean_token_f1"],
        rel_tol=0,
        abs_tol=1e-10,
    ):
        raise ValueError("privileged results differ between the two original controls")

    event = cross["controlled_authored_event"]
    ea = event["arms"]
    if (
        ea["entity_time"]["strict_correct"] != 8
        or ea["organized"]["strict_correct"] != 8
        or ea["organized"]["correct_with_full_public_citation_path"] != 4
        or event["calibration_stable_under_leave_one_out"] is not False
    ):
        raise ValueError("historical event result or graph/citation no-go was modified")
    visibility = publisher["publisher_privileged_support_visible_effect"]
    if (
        visibility["k4_missing_publisher_support"]["questions"] != 5
        or visibility["k4_already_had_publisher_support"]["questions"] != 8
    ):
        raise ValueError("publisher support source strata have drifted")

    return dict(
        schema=SCHEMA,
        source_zip_sha256=dict(cross["source_zip_sha256"])
        | dict(
            publisher_plan=publisher["exact_zip_sha256"]["plan"],
            publisher_model=publisher["exact_zip_sha256"]["reader"],
            publisher_score=publisher["exact_zip_sha256"]["score"],
        ),
        frozen_reader_identity=cross["reader_identity"],
        real_calibration_calls=40,
        real_authored_event_evaluation_calls=72,
        real_label_blind_locomo_reader_calls=32,
        real_publisher_privileged_reader_calls=16,
        original_real_model_calls=160,
        distinct_evaluation_questions=24,
        distinct_calibration_questions=8,
        public_locomo_source_family_proxies=2,
        independent_future_source_families=0,
        event=dict(
            full_path_strict_correct=ea["entity_time"]["strict_correct"],
            organized_strict_correct=ea["organized"]["strict_correct"],
            organized_correct_with_full_public_citation_path=ea["organized"][
                "correct_with_full_public_citation_path"
            ],
            incremental_organized_strict_correct=0,
        ),
        comparable_published_locomo_f1=matched,
        publisher_support_is_annotation_privileged_not_online=True,
        pooled_answer_accuracy=None,
        answer_metrics_incompatible=True,
        independent_human_sufficiency_reviews=0,
        independent_semantic_citation_precision=None,
        calibrated_topk_stable=False,
        graph_incremental_task_accuracy_proven=False,
        parameter_memory_gain_established=False,
        parametric_memory_training_qualified=False,
        production_accepted=False,
        research_disposition=(
            "NO_GO: privileged context sensitivity is not learned-memory gain; "
            "require new family-disjoint evidence and independently verified "
            "sufficient spans before parameter training"
        ),
    )


def audit(paths: dict[str, Path]) -> dict:
    if set(paths) != set(CROSS_NAMES) | set(PUBLISHER_NAMES):
        raise ValueError("exact ten externally pinned research artifacts required")
    from reader_cross_population_gate import PINS as CROSS_PINS, reconcile
    from locomo_publisher_completion_receipt import audit as publisher_audit

    if set(CROSS_PINS) != set(CROSS_NAMES):
        raise ValueError("underlying cross-population source census changed")
    cross = reconcile({name: paths[name] for name in CROSS_NAMES})
    publisher = publisher_audit(*(paths[name] for name in PUBLISHER_NAMES))
    return join_verified(cross, publisher)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (*CROSS_NAMES, *PUBLISHER_NAMES):
        parser.add_argument(name, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    answer = audit(
        {name: getattr(args, name) for name in (*CROSS_NAMES, *PUBLISHER_NAMES)}
    )
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(answer, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(
        json.dumps(
            {
                "actual_calls": answer["original_real_model_calls"],
                "production_accepted": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
