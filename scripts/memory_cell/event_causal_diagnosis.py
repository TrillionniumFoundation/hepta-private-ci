"""Paired reader/evidence fault attribution on ACTUAL sealed answer records.

No classifier is trained here. An authored program-support set is a controlled
ceiling, not a human-adjudicated sufficient context. Missing executions remain
unknown in paired comparisons, not failures silently counted as wrong answers.
"""

from collections import Counter

ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)


def _pair(group, left, right):
    a, b = group[left], group[right]
    if a["status"] != "succeeded" or b["status"] != "succeeded":
        return "unobserved"
    delta = int(b["strict_task_success"]) - int(a["strict_task_success"])
    return "win" if delta > 0 else "loss" if delta < 0 else "tie"


def diagnose(records, expected):
    """Partition fixed cases without selecting a winner from held-out labels.

    Contrasts are (right - left). Unknown pairs widen the identification bounds
    by one planned task each. Data are deliberately NOT treated as independent
    source families, and a controlled support condition is never rebranded as a
    human-verified oracle.
    """
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("fixed unique question census required")
    groups = {}
    for row in records:
        qid, arm = row["question_id"], row["arm"]
        if qid not in expected or arm not in ARMS:
            raise ValueError("out-of-census observed outcome")
        group = groups.setdefault(qid, {})
        if arm in group or row["status"] not in ("succeeded", "failed"):
            raise ValueError("duplicate or invalid observed outcome")
        if (
            row["status"] == "succeeded"
            and type(row.get("strict_task_success")) is not bool
        ):
            raise ValueError("strict task outcome must be recorded, not inferred")
        group[arm] = row
    if any(set(groups.get(qid, {})) != set(ARMS) for qid in expected):
        raise ValueError("incomplete reader control census")

    cases, counts, ablations, strata = [], Counter(), Counter(), {}
    comparisons = {
        "organized_minus_hybrid": Counter(),
        "program_support_minus_hybrid": Counter(),
        "without_prerequisite_minus_program_support": Counter(),
    }
    for qid in expected:
        group = groups[qid]
        if len({row["candidate_digest"] for row in group.values()}) != 1:
            raise ValueError("unmatched retrieval pool in reader controls")
        kinds = {row.get("kind", "unspecified") for row in group.values()}
        if len(kinds) != 1 or not all(isinstance(k, str) for k in kinds):
            raise ValueError("task kind differs between paired conditions")
        kind = next(iter(kinds))
        identities = {
            (
                row["receipt"]["reader_identity"],
                row["receipt"]["reader_profile"],
                row["receipt"]["token_limit"],
            )
            for row in group.values()
            if row["status"] == "succeeded"
        }
        if len(identities) > 1:
            raise ValueError("reader or budget changed within paired conditions")
        correct = {
            arm: row["strict_task_success"] if row["status"] == "succeeded" else None
            for arm, row in group.items()
        }
        covered = {
            arm: row.get("required_sources_covered")
            if row["status"] == "succeeded"
            else None
            for arm, row in group.items()
        }
        if any(v is not None and type(v) is not bool for v in covered.values()):
            raise ValueError("invalid original-support coverage observation")
        failed = [arm for arm in ARMS if correct[arm] is None]

        if failed:
            category = "incomplete_execution"
        elif correct["empty"]:
            category = "no_evidence_control_already_succeeds"
        elif not correct["program_support"]:
            category = "controlled_support_reader_or_task_failure"
        elif correct["hybrid"]:
            category = "strong_rag_already_succeeds"
        elif correct["organized"]:
            category = (
                "memory_organization_recovers_missing_support"
                if covered["hybrid"] is False and covered["organized"] is True
                else "organization_or_read_path_recovers_answer"
            )
        elif covered["hybrid"] is False and covered["organized"] is False:
            category = "both_retrieval_and_organization_miss_support"
        elif covered["organized"] is True:
            category = "organized_support_present_but_answer_wrong"
        elif covered["hybrid"] is True:
            category = "hybrid_support_present_but_answer_wrong"
        else:
            category = "oracle_only_other_paths_unresolved"

        ablation = (
            "unobserved"
            if correct["program_support"] is None
            or correct["without_prerequisite"] is None
            else "not_demonstrated_necessary"
            if correct["program_support"] and correct["without_prerequisite"]
            else "omission_sensitive_not_a_necessity_proof"
            if correct["program_support"] and not correct["without_prerequisite"]
            else "oracle_control_unsuccessful"
        )
        cases.append(
            dict(
                question_id=qid,
                kind=kind,
                category=category,
                ablation=ablation,
                strict_success=correct,
                required_support_covered=covered,
                failed_arms=failed,
                candidate_digest=group["hybrid"]["candidate_digest"],
            )
        )
        counts[category] += 1
        ablations[ablation] += 1
        bucket = strata.setdefault(kind, Counter())
        bucket["planned"] += 1
        bucket[category] += 1
        for arm in ARMS:
            bucket[arm + "_success"] += correct[arm] is True
            bucket[arm + "_failed"] += correct[arm] is None
        for title, left, right in (
            ("organized_minus_hybrid", "hybrid", "organized"),
            ("program_support_minus_hybrid", "hybrid", "program_support"),
            (
                "without_prerequisite_minus_program_support",
                "program_support",
                "without_prerequisite",
            ),
        ):
            comparisons[title][_pair(group, left, right)] += 1

    n = len(expected)
    paired = {}
    for label, observed in comparisons.items():
        unknown = observed["unobserved"]
        difference = observed["win"] - observed["loss"]
        paired[label] = dict(
            wins=observed["win"],
            losses=observed["loss"],
            ties=observed["tie"],
            unobserved=unknown,
            observed_pair_success_delta=(
                difference / (n - unknown) if n != unknown else None
            ),
            all_planned_delta_lower=(difference - unknown) / n,
            all_planned_delta_upper=(difference + unknown) / n,
        )
    return dict(
        schema="hepta.event-reader.paired-causal-diagnosis.v1",
        planned_questions=n,
        observed_questions=n - counts["incomplete_execution"],
        cases=cases,
        attribution_counts=dict(sorted(counts.items())),
        ablation_dispositions=dict(sorted(ablations.items())),
        hybrid_support_present_but_answer_wrong=sum(
            case["strict_success"]["hybrid"] is False
            and case["required_support_covered"]["hybrid"] is True
            for case in cases
        ),
        controlled_premise_necessity_proven=False,
        by_task_kind={k: dict(sorted(v.items())) for k, v in sorted(strata.items())},
        paired_contrasts=paired,
        program_support_is_human_verified=False,
        original_evidence_preservation_verified_by_this_scorer=False,
        reader_capacity_comparison_is_a_separate_axis=True,
        independent_future_source_families=0,
        semantic_citation_precision=None,
        superiority_established=False,
        policy_or_parametric_learning_qualified=False,
        production_accepted=False,
    )
