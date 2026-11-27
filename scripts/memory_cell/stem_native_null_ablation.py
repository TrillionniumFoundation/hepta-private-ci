"""Label-free native null-vs-source choice; post-policy answerability audit.

The experiment's six forced-top1 arms and Reader requests are UNCHANGED.
The zero-offset null choice is a diagnostic, never used to generate answers
or select a checkpoint. Native labels are consulted only by the later
read-only summarizer after every original policy answer has been saved.
"""

from collections import defaultdict
import math

from native import digest

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


def observe_null_choice(logits, candidate_ids, actual_forced_selection):
    n = len(candidate_ids)
    if (
        not isinstance(candidate_ids, (tuple, list))
        or not isinstance(logits, (list, tuple))
        or not 0 <= n <= 64
        or len(logits) != n + 1
        or len(set(candidate_ids)) != n
        or any(not isinstance(x, str) or not x for x in candidate_ids)
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in logits)
    ):
        raise ValueError("unbound or nonfinite null-choice Head logits")
    best = min(range(n), key=lambda i: (-logits[i], candidate_ids[i])) if n else None
    if actual_forced_selection != best:
        raise ValueError("null diagnostic differs from actual forced top-1")
    margin = logits[-1] - logits[best] if best is not None else None
    if margin is not None and not math.isfinite(margin):
        raise ValueError("nonfinite null-vs-evidence margin")
    abstain = best is None or margin >= 0
    return dict(
        schema="hepta.stem-label-free-null-counterfactual.v1",
        candidate_count=n,
        observed_forced_top1_index=best,
        native_zero_offset_null_logit=logits[-1],
        best_candidate_logit=logits[best] if best is not None else None,
        null_minus_best_candidate=margin,
        zero_offset_would_abstain=abstain,
        counterfactual_choice=None if abstain else best,
        logit_vector_sha256=digest((tuple(candidate_ids), tuple(logits))),
        original_forced_top1_unchanged=True,
        actual_reader_answer_not_recomputed=True,
        posthoc_labels_used_to_select_cutoff=False,
    )


def review_null_counterfactual(plan, scored, targets):
    registered = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in plan["questions"][phase]
        for arm in ARMS
    }
    questions = {qid for phase in PHASES for qid in plan["questions"][phase]}
    if (
        tuple(plan["arms"]) != ARMS
        or tuple(plan["curriculum_attempted_examples"]) != STAGES
        or any(len(plan["questions"][phase]) != 8 for phase in PHASES)
        or len(questions) != 32
        or not isinstance(targets, dict)
        or set(targets) != questions
        or len(scored) != 576
    ):
        raise ValueError("unaligned preregistered null/forced-top1 census")
    seen, by_arm = set(), defaultdict(list)
    for row in scored:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        if key not in registered or key in seen:
            raise ValueError("duplicate or unregistered null diagnostic question")
        if row.get("status") not in ("succeeded", "failed"):
            raise ValueError("unknown original forced policy execution status")
        seen.add(key)
        target = targets[row["question_id"]]
        if (
            type(target.unanswerable) is not bool
            or not isinstance(target.evidence, (tuple, list))
            or not isinstance(target.unresolved_evidence, (tuple, list))
        ):
            raise ValueError("invalid native answerability label")
        if target.unanswerable:
            category = "native-unanswerable"
        elif target.unresolved_evidence or not target.evidence:
            category = "native-support-unresolved"
        else:
            category = "answerable-native-document-support"

        receipt = row.get("null_counterfactual")
        if receipt is not None:
            if (
                receipt.get("schema") != "hepta.stem-label-free-null-counterfactual.v1"
                or receipt.get("original_forced_top1_unchanged") is not True
                or receipt.get("posthoc_labels_used_to_select_cutoff") is not False
                or "selected" not in row
                or receipt["observed_forced_top1_index"] != row["selected"]
                or receipt["counterfactual_choice"]
                != (None if receipt["zero_offset_would_abstain"] else row["selected"])
            ):
                raise ValueError("altered forced choice or null diagnostic receipt")
        if receipt is None and "selected" in row:
            raise ValueError("missing null score for observed forced selection")
        if receipt is not None:
            margin = receipt["null_minus_best_candidate"]
            count = receipt["candidate_count"]
            if (
                type(count) is not int
                or not 0 <= count <= 64
                or (count == 0 and (margin is not None or row["selected"] is not None))
                or (
                    count > 0
                    and (type(margin) not in (int, float) or not math.isfinite(margin))
                )
                or receipt["zero_offset_would_abstain"]
                is not (count == 0 or margin >= 0)
                or (
                    count > 0
                    and (
                        type(row["selected"]) is not int
                        or not 0 <= row["selected"] < count
                    )
                )
            ):
                raise ValueError("inconsistent zero-offset native null choice")
        source_correctness = row.get("source_choice_correct")
        native_scored = (
            receipt is not None
            and category != "native-support-unresolved"
            and type(source_correctness) is int
            and source_correctness in (0, 1)
        )
        if native_scored:
            if category == "native-unanswerable":
                if source_correctness != int(row["selected"] is None):
                    raise ValueError("forged baseline native abstention correctness")
                actual = source_correctness
                alternate = int(receipt["zero_offset_would_abstain"])
            else:
                actual = source_correctness
                alternate = 0 if receipt["zero_offset_would_abstain"] else actual
        else:
            actual = alternate = None
        by_arm[(row["stage"], row["phase"], row["arm"])].append(
            dict(
                question_id=row["question_id"],
                native_answerability_category=category,
                reader_generation_status=row["status"],
                null_score_observed=receipt is not None,
                fixed_cutoff_zero_only=True,
                original_source_correctness=actual,
                null_counterfactual_source_correctness=alternate,
                native_source_choice_delta=(
                    alternate - actual if native_scored else None
                ),
                zero_offset_would_abstain=(
                    receipt["zero_offset_would_abstain"] if receipt else None
                ),
                original_policy_answer_bytes_unchanged=True,
                counterfactual_reader_answer_not_evaluated=True,
                independently_adjudicated_entailment=False,
            )
        )
    if set(seen) != registered:
        raise ValueError("missing original six-arm null-counterfactual attempt")
    summaries = {}
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS:
                rows = by_arm[(stage, phase, arm)]
                if len(rows) != 8:
                    raise ValueError("null diagnosis lost phase denominator")
                scored_delta = [
                    x["native_source_choice_delta"]
                    for x in rows
                    if x["native_source_choice_delta"] is not None
                ]
                unobserved = len(rows) - len(scored_delta)
                observed_sum = sum(scored_delta)
                summaries[f"{stage}/{phase}/{arm}"] = dict(
                    attempted=8,
                    native_unanswerable_count=sum(
                        x["native_answerability_category"] == "native-unanswerable"
                        for x in rows
                    ),
                    native_support_unresolved_count=sum(
                        x["native_answerability_category"]
                        == "native-support-unresolved"
                        for x in rows
                    ),
                    source_compared=len(scored_delta),
                    unobserved_or_unresolved=unobserved,
                    zero_offset_predicted_abstentions=sum(
                        x["zero_offset_would_abstain"] is True for x in rows
                    ),
                    native_unanswerable_recovered=sum(
                        x["native_answerability_category"] == "native-unanswerable"
                        and x["native_source_choice_delta"] == 1
                        for x in rows
                    ),
                    native_answerable_harmed_by_abstention=sum(
                        x["native_answerability_category"]
                        == "answerable-native-document-support"
                        and x["native_source_choice_delta"] == -1
                        for x in rows
                    ),
                    native_source_correctness_delta_sum=observed_sum,
                    all_planned_native_correctness_delta_bounds=[
                        (observed_sum - unobserved) / 8,
                        (observed_sum + unobserved) / 8,
                    ],
                    policy_outputs_unchanged=True,
                    extra_reader_calls=0,
                    production_accepted=False,
                )
    return dict(
        schema="hepta.stem-no-tuned-null-ablation.v1",
        cutoff_source="native Head null-vs-top1 logits; offset exactly zero",
        label_free_during_selection=True,
        counterfactual_does_not_recompute_reader_answers=True,
        original_policy_counts_preserved=576,
        original_policy_is_forced_top1=True,
        native_document_support_not_entailment=True,
        posthoc_exploratory_not_preregistered_policy=True,
        per_arm_phase_checkpoint=summaries,
        production_accepted=False,
        semantic_citation_precision=None,
    )
