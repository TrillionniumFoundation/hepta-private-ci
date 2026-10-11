"""Matched Reader gain over no-evidence, without conflating retrieval and QA.

Compare final-checkpoint frozen ranker + original fixed Reader against a
separately instantiated byte-identical Reader with zero supplied evidence.
Neither learned Head nor adapted Encoder enters these controlled comparisons.
Failures, unscorable targets and unverified citations remain explicit.
"""

from collections import defaultdict
import math


PHASES = ("select", "retention", "test", "transfer")


def compare_frozen_to_no_evidence(scored_policies, no_evidence_rows,
                                  targets, diagnose, *, final_stage=48):
    if len(no_evidence_rows) != 32:
        raise ValueError("zero-evidence control must retain all 32 questions")
    controls = {}
    for row in no_evidence_rows:
        key = (row["phase"], row["question_id"])
        if key in controls or row["phase"] not in PHASES:
            raise ValueError("duplicate or unregistered Reader control")
        controls[key] = row
    frozen = {}
    for row in scored_policies:
        if row["stage"] != final_stage or row["arm"] != "frozen_rerank":
            continue
        key = (row["phase"], row["question_id"])
        if key in frozen or row["phase"] not in PHASES:
            raise ValueError("ambiguous final checkpoint Reader comparator")
        frozen[key] = row
    if (
        len(frozen) != 32
        or set(controls) != set(frozen)
        or any(sum(key[0] == phase for key in controls) != 8 for phase in PHASES)
    ):
        raise ValueError("unpaired or incomplete final-reader census")
    by_phase = defaultdict(list)
    for key in sorted(controls):
        p, c = frozen[key], controls[key]
        if (
            p["family"] != c["family"]
            or p["question_id"] not in targets
            or c["evidence_count"] != 0
        ):
            raise ValueError("misbound evidence/no-evidence comparison")
        original_ok = p["status"] == "succeeded"
        empty_ok = c["status"] == "succeeded"
        supplied_count = 0
        if original_ok:
            received = p["receipt"]["delivered_evidence"]
            if not isinstance(received, list) or len(received) > 1:
                raise ValueError("original Reader supplied evidence drift")
            supplied_count = len(received)
        if empty_ok and c["receipt"]["delivered_evidence"] != []:
            raise ValueError("zero-evidence control received a source")
        row = dict(
            phase=key[0], question_id=key[1], family=p["family"],
            frozen_reader_succeeded=original_ok,
            zero_evidence_reader_succeeded=empty_ok,
            actual_frozen_evidence_count=supplied_count,
            scored_pair=False,
            diagnostic_answer_f1_delta=None,
            gold_evidence_sufficiency_independently_verified=False,
            source_correctness_evaluated_by_this_control=False,
            semantic_citation_precision=None,
        )
        if original_ok and empty_ok:
            original_f1 = diagnose(p["answer"], targets[key[1]])
            no_evidence_f1 = diagnose(c["answer"], targets[key[1]])
            if original_f1 is not None and no_evidence_f1 is not None:
                if any(type(v) not in (int, float) or not math.isfinite(v)
                       or not 0 <= v <= 1
                       for v in (original_f1, no_evidence_f1)):
                    raise ValueError("invalid paired Reader diagnostic score")
                row.update(
                    scored_pair=True,
                    frozen_reader_f1=original_f1,
                    zero_evidence_reader_f1=no_evidence_f1,
                    diagnostic_answer_f1_delta=original_f1 - no_evidence_f1,
                )
        by_phase[key[0]].append(row)
    summaries = {}
    for phase, rows in sorted(by_phase.items()):
        successes = [row["diagnostic_answer_f1_delta"]
                     for row in rows if row["scored_pair"]]
        n = len(rows)
        remaining = n - len(successes)
        observed_sum = math.fsum(successes)
        summaries[phase] = dict(
            attempted=n,
            frozen_reader_succeeded=sum(r["frozen_reader_succeeded"] for r in rows),
            zero_evidence_reader_succeeded=sum(
                r["zero_evidence_reader_succeeded"] for r in rows
            ),
            both_answered_and_scored=len(successes),
            omitted_or_failed_pairs=remaining,
            paired_diagnostic_delta_mean=(
                observed_sum / len(successes) if successes else None
            ),
            all_planned_answer_delta_bounds=[
                (observed_sum - remaining) / n,
                (observed_sum + remaining) / n,
            ],
            frozen_supplied_source_count=sum(
                r["actual_frozen_evidence_count"] > 0 for r in rows
            ),
            independent_source_families_authenticated=False,
            superiority_claim=False,
            semantic_citation_precision=None,
        )
    return dict(
        schema="hepta.stem-evidence-vs-empty-reader.v1",
        matched_pairs=32,
        stage=final_stage,
        controls_learnt_parameters=False,
        same_read_only_reader_weights_and_prompt=True,
        independent_correct_support_verification=False,
        per_phase=summaries,
        pairs=[r for phase in PHASES for r in by_phase[phase]],
        qualified_evidence_sufficiency=False,
        production_accepted=False,
    )
