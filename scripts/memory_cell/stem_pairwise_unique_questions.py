"""Deduplicate immutable source-only Shadow observations by native question.

This is a bounded post-hoc *source ranking* audit, not new learning, a Reader
answer, sufficient-evidence adjudication, or an independent family trial.
Aggregate weak-support gains do not identify which question gained when
multiple source choices flipped in the same checkpoint/arm. Return honest
lower/upper DISTINCT QUESTION bounds instead of inventing gold labels.
"""

from collections import defaultdict
from itertools import combinations

STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = ("pairwise_linear", "pairwise_gated")


def _possible_unique(changed_by_group, gain_by_group, question_order):
    """Enumerate exact cardinality-compatible unions, at most eight QIDs."""
    positions = {qid: i for i, qid in enumerate(question_order)}
    possible = {0}
    for key in sorted(changed_by_group):
        changes = changed_by_group[key]
        gains = gain_by_group[key]
        if type(gains) is not int or not 0 <= gains <= len(changes):
            raise ValueError("weak-label gains exceed actual changed top-1 decisions")
        options = {
            sum(1 << positions[qid] for qid in selected)
            for selected in combinations(changes, gains)
        }
        possible = {prior | new for prior in possible for new in options}
        if not possible or len(possible) > 256:
            raise ValueError("out-of-bounds question union census")
    sizes = [mask.bit_count() for mask in possible]
    return [min(sizes), max(sizes)]


def unique_shadow_question_bounds(plan, decisions, posthoc):
    """Dedupe 192 original Shadow decisions after outer immutable ZIP audit.

    The native weak-source posthoc payload contains aggregate 8-item group
    totals, not per-question support verdicts. An exact unique-question count
    is issued only if lower and upper bounds coincide.
    """
    cohorts = plan["questions"]
    if (
        set(cohorts) != {"train", *PHASES}
        or len(cohorts["train"]) != 48
        or any(len(cohorts[p]) != 8 or len(set(cohorts[p])) != 8 for p in PHASES)
        or len({q for group in cohorts.values() for q in group}) != 80
        or len(decisions) != 192
        or not isinstance(posthoc, dict)
        or posthoc.get("schema") not in (
            "hepta.stem-pairwise-native-source-only-shadow.v1",
            "hepta.stem-pairwise-native-source-only-shadow.v2",
        )
        or posthoc.get("production_accepted") is not False
        or posthoc.get("independently_established_generalization") is not False
    ):
        raise ValueError("unregistered or falsely promoted Shadow census")
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES for phase in PHASES
        for qid in cohorts[phase] for arm in ARMS
    }
    choices, families, by_group = {}, {}, defaultdict(list)
    for row in decisions:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        if key not in expected or key in choices:
            raise ValueError("duplicate or unregistered Shadow decision")
        if (
            row["status"] not in ("succeeded", "failed")
            or not isinstance(row.get("family"), str) or not row["family"]
            or row.get("actual_reader_calls") != 0
        ):
            raise ValueError("Shadow model status, source family or Reader drift")
        qid = row["question_id"]
        previous = families.setdefault(qid, row["family"])
        if previous != row["family"]:
            raise ValueError("same question changed source family")
        choices[key] = row
        by_group[(row["stage"], row["phase"], row["arm"])].append(row)
    if set(choices) != expected:
        raise ValueError("incomplete 192 Shadow original selections")

    group_receipts = posthoc.get("by_checkpoint_phase_arm")
    if not isinstance(group_receipts, dict) or len(group_receipts) != 24:
        raise ValueError("original Shadow weak-source groups are incomplete")
    phase_groups, review = defaultdict(dict), defaultdict(list)
    results = {}
    total_gain_events = total_regression_events = total_flips = 0
    for stage in STAGES:
        for phase in PHASES:
            for arm in ARMS:
                key = stage, phase, arm
                label = f"{stage}/{phase}/{arm}"
                source = group_receipts.get(label)
                records = by_group[key]
                if not isinstance(source, dict) or len(records) != 8:
                    raise ValueError("missing checkpoint/phase/arm Shadow source census")
                changed = []
                for row in records:
                    if row["status"] != "succeeded":
                        continue
                    new = row.get("selected")
                    frozen = row.get("original_frozen_selected")
                    if (
                        type(new) is not int or type(frozen) is not int
                        or not 0 <= new < row["candidate_count"]
                        or not 0 <= frozen < row["candidate_count"]
                    ):
                        raise ValueError("unbound observed Shadow source selection")
                    if new != frozen:
                        changed.append(row["question_id"])
                        review[(phase, row["question_id"])].append(
                            dict(checkpoint=stage, arm=arm,
                                 original_top1=frozen, shadow_top1=new)
                        )
                gains = source.get("native_weak_support_gains")
                regressions = source.get("native_weak_support_regressions")
                if (
                    source.get("attempted") != 8
                    or source.get("selection_changed") != len(changed)
                    or type(gains) is not int or type(regressions) is not int
                    or gains < 0 or regressions < 0
                    or gains + regressions > len(changed)
                ):
                    raise ValueError("weak native gains exceed original changed choices")
                changed = tuple(sorted(changed))
                phase_groups[phase][key] = dict(
                    changed=changed, gains=gains, regressions=regressions,
                )
                total_flips += len(changed)
                total_gain_events += gains
                total_regression_events += regressions
                results[label] = dict(
                    changed_source_choice_events=len(changed),
                    weak_source_gain_events=gains,
                    weak_source_regression_events=regressions,
                    distinct_changed_questions=len(set(changed)),
                )
    if set(group_receipts) != set(results):
        raise ValueError("unregistered original Shadow checkpoint group")

    phase_summary = {}
    for phase in PHASES:
        group = phase_groups[phase]
        changed_by = {key: item["changed"] for key, item in group.items()}
        gain_by = {key: item["gains"] for key, item in group.items()}
        loss_by = {key: item["regressions"] for key, item in group.items()}
        flipped = {q for item in group.values() for q in item["changed"]}
        gain_bound = _possible_unique(changed_by, gain_by, cohorts[phase])
        loss_bound = _possible_unique(changed_by, loss_by, cohorts[phase])
        phase_summary[phase] = dict(
            registered_original_questions=8,
            repeated_stage_arm_observations=48,
            changed_choice_events=sum(len(v) for v in changed_by.values()),
            changed_unique_questions=len(flipped),
            changed_unique_source_families=len({families[q] for q in flipped}),
            weak_gain_events=sum(gain_by.values()),
            weak_regression_events=sum(loss_by.values()),
            unique_weak_gain_question_bounds=gain_bound,
            unique_weak_regression_question_bounds=loss_bound,
            exact_unique_weak_gain_count=(
                gain_bound[0] if gain_bound[0] == gain_bound[1] else None
            ),
            event_counts_are_not_independent_test_samples=True,
        )

    def sum_bounds(phases, name):
        return [
            sum(phase_summary[p][name][position] for p in phases)
            for position in (0, 1)
        ]

    worklist = []
    for phase, qid in sorted(review):
        worklist.append(dict(
            phase=phase,
            question_id=qid,
            source_family=families[qid],
            actual_rank_changes=sorted(review[(phase, qid)],
                                       key=lambda v: (v["checkpoint"], v["arm"])),
            weak_source_gain_attributable_to_this_question=None,
            answer_or_semantic_citation_reviewed=False,
            externally_qualified_reviewer_present=False,
        ))
    gain_total = sum_bounds(PHASES, "unique_weak_gain_question_bounds")
    heldout = sum_bounds(("test", "transfer"), "unique_weak_gain_question_bounds")
    return dict(
        schema="hepta.stem-pairwise-distinct-question-shadow.v1",
        original_policy_arms_unchanged=True,
        original_shadow_decision_count=len(decisions),
        repeated_rank_flip_events=total_flips,
        distinct_changed_question_count=len(review),
        weak_document_source_gain_events=total_gain_events,
        weak_document_source_regression_events=total_regression_events,
        distinct_question_gain_bounds=gain_total,
        distinct_test_transfer_question_gain_bounds=heldout,
        exact_distinct_question_gain_count=(
            gain_total[0] if gain_total[0] == gain_total[1] else None
        ),
        per_phase=phase_summary,
        original_stage_phase_arm_counts=results,
        changed_question_review_worklist=worklist,
        source_labels_not_per_question_in_aggregate=True,
        no_gold_labels_or_reader_answers_imported=True,
        checkpoint_repetitions_not_independent_questions=True,
        independent_source_family_generalization_proven=False,
        independently_verified_evidence_entailment=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )
