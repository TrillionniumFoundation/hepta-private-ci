"""Read-only refusal-to-promote gate on native Stem results.

An all-success CI status is operational evidence, not transferable learning.
Require actual matched source/answer outcomes and independently judged citation
support before a scaling claim. Never turn missing reviewer evidence into zero.
"""
from collections import defaultdict
import math

ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")
PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)


def audit_nonpromotion(report):
    metrics = report["metrics"]
    expected = {f"{stage}/{phase}/{arm}"
                for stage in STAGES for phase in PHASES for arm in ARMS}
    if set(metrics) != expected or report.get("logical_policy_attempts") != 576:
        raise ValueError("incomplete or modified original 576-policy census")
    if report.get("production_accepted") is not False:
        raise ValueError("unqualified native run promoted itself")
    by_arm = defaultdict(lambda: dict(
        compared_phase_checkpoints=0, identical_source_accuracy=0,
        identical_answer_f1=0, support_source_accuracy_superior=0,
        reader_answer_f1_superior=0, paired_answer_f1_unscored=0,
    ))
    total_attempts, failed_attempts, citations = 0, 0, 0
    for stage in STAGES:
        for phase in PHASES:
            base = metrics[f"{stage}/{phase}/frozen_rerank"]
            for arm in ARMS:
                row = metrics[f"{stage}/{phase}/{arm}"]
                if (row["attempted"] != 8 or
                        row["succeeded"] + row["failed"] != 8 or
                        row["emitted_citation_markers"] < 0 or
                        row["delivered_citation_markers"] < 0 or
                        row["delivered_citation_markers"] >
                        row["emitted_citation_markers"]):
                    raise ValueError("corrupt policy success/citation denominator")
                total_attempts += row["attempted"]
                failed_attempts += row["failed"]
                citations += row["emitted_citation_markers"]
                if arm == "frozen_rerank":
                    continue
                group = by_arm[arm]
                group["compared_phase_checkpoints"] += 1
                for field, name, higher in (
                    ("source_accuracy", "identical_source_accuracy",
                     "support_source_accuracy_superior"),
                    ("diagnostic_f1", "identical_answer_f1",
                     "reader_answer_f1_superior"),
                ):
                    a, b = row[field], base[field]
                    if a is None or b is None:
                        group["paired_answer_f1_unscored"] += 1
                    elif (not all(type(v) in (float, int) and
                                  math.isfinite(v) and 0 <= v <= 1 for v in (a, b))):
                        raise ValueError("nonfinite native outcome")
                    elif a == b:
                        group[name] += 1
                    elif a > b:
                        group[higher] += 1
    if total_attempts != 576:
        raise ValueError("policy denominator drift")
    results = dict(by_arm)
    observed_outcome_improvement = any(
        x["support_source_accuracy_superior"] or
        x["reader_answer_f1_superior"] for x in results.values()
    )
    return dict(
        schema="hepta.stem-native-nonpromotion-gate.v1",
        status="not-qualified",
        audited_policy_attempts=total_attempts,
        policy_execution_failures=failed_attempts,
        citation_markers=citations,
        learning_arms=results,
        any_aggregate_source_or_answer_gain=bool(observed_outcome_improvement),
        aggregate_equivalence_not_proof_of_identical_question_choices=True,
        independent_semantic_citation_precision=None,
        production_accepted=False,
        scale_out_permitted=False,
        next_required_evidence=(
            "exact per-question frozen-paired source changes, heldout answer gain, "
            "independent semantic citation audit and per-arm TCO"
        ),
    )
