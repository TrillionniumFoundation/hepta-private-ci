"""Sealed 32-case pairwise Shadow-to-frozen-Reader diagnostic.

All 192 shadow top-1 choices and 576 original six-arm decisions are committed
before this separately accounted Reader experiment. No training/test labels,
source-support votes or citation verdicts enter generation. This is NOT
a seventh production Head, nor independently adjudicated citation correctness.
"""

from collections import defaultdict
from dataclasses import asdict
import math
import re

from native import digest

STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
TEST_PHASES = ("test", "transfer")
ARMS = ("pairwise_linear", "pairwise_gated")


def _registered(questions, choices, frozen_attempts):
    if (
        set(questions) != {"train", *PHASES}
        or len(questions["train"]) != 48
        or any(len(questions[phase]) != 8 for phase in PHASES)
        or len({q.identity for qs in questions.values() for q in qs}) != 80
    ):
        raise ValueError("incomplete preregistered native question census")
    expected = {
        (stage, phase, q.identity, arm)
        for stage in STAGES for phase in PHASES
        for q in questions[phase] for arm in ARMS
    }
    decisions = {}
    for choice in choices:
        key = (choice["stage"], choice["phase"], choice["question_id"], choice["arm"])
        if key not in expected or key in decisions:
            raise ValueError("duplicate or nonregistered Shadow decision")
        if (
            choice["status"] not in ("succeeded", "failed")
            or choice["actual_reader_calls"] != 0
            or choice["training_labels_or_test_gold_in_answer"] is not False
        ):
            raise ValueError("non-blind or already answered Shadow choice")
        decisions[key] = choice
    if len(decisions) != 192 or set(decisions) != expected:
        raise ValueError("incomplete original 192 Shadow decision census")
    frozen = {}
    if len(frozen_attempts) != 576:
        raise ValueError("incomplete original six-arm policy denominator")
    for item in frozen_attempts:
        if (
            item.get("arm") == "frozen_rerank"
            and item.get("stage") == 48
            and item.get("phase") in TEST_PHASES
        ):
            key = item["phase"], item["question_id"]
            if key in frozen:
                raise ValueError("duplicated final-checkpoint frozen Reader")
            frozen[key] = item
    expected_frozen = {
        (phase, q.identity) for phase in TEST_PHASES for q in questions[phase]
    }
    if set(frozen) != expected_frozen:
        raise ValueError("missing fixed Reader comparator for changed Shadow")
    return decisions, frozen


def run_final_shadow_reader(
    questions, choices, frozen_attempts, evidence_for, answer,
    *, reader_identity, reader_profile,
):
    """Generate 32 raw final-checkpoint Shadow answers, before this review's gold.

    evidence_for(q, index) must bind the exact original frozen-Encoder
    query/pool/selected-window triple; answer(q,evidence,key) uses the
    already loaded isolated Reader cache, not the original policy Reader.
    """
    decisions, frozen = _registered(questions, choices, frozen_attempts)
    if (
        not callable(evidence_for) or not callable(answer)
        or not isinstance(reader_identity, str) or not reader_identity
        or not isinstance(reader_profile, str) or not reader_profile
    ):
        raise ValueError("missing isolated fixed Reader callback or pin")
    results = []
    for phase in TEST_PHASES:
        for q in questions[phase]:
            baseline = frozen[(phase, q.identity)]
            for arm in ARMS:
                shadow = decisions[(48, phase, q.identity, arm)]
                if (
                    shadow.get("family") != baseline.get("family")
                    or shadow.get("cell") != baseline.get("cell")
                    or not shadow.get("pool_digest")
                    or (baseline.get("pool_digest") is not None and
                        baseline["pool_digest"] != shadow["pool_digest"])
                ):
                    raise ValueError("Shadow and frozen source identity drift")
                item = dict(
                    schema="hepta.stem-final-shadow-reader-control.v1",
                    stage=48, phase=phase, question_id=q.identity, arm=arm,
                    source_family=baseline["family"],
                    cell=baseline["cell"], source_pool_digest=shadow["pool_digest"],
                    frozen_selected=baseline.get("selected"),
                    shadow_selected=shadow.get("selected"),
                    shadow_fit_or_decision_status=shadow["status"],
                    original_reader_status=baseline["status"],
                    changed_frozen_selected_source=(
                        shadow.get("selected") != baseline["selected"]
                        if shadow["status"] == "succeeded"
                        and type(baseline.get("selected")) is int
                        else None
                    ),
                    role="post-six-arm-isolated-matched-shadow-Reader-not-production",
                    original_576_answers_unchanged=True,
                    native_target_passed_to_generator=False,
                    independent_semantic_citation_verdict=False,
                )
                if shadow["status"] == "failed":
                    item.update(status="unavailable", reason="shadow-decision-failed")
                    results.append(item)
                    continue
                try:
                    choice = shadow["selected"]
                    if (
                        type(choice) is not int
                        or not 0 <= choice < shadow["candidate_count"]
                        or shadow.get("original_frozen_selected") != baseline.get("selected")
                    ):
                        raise ValueError("unbound Shadow and frozen selected windows")
                    evidence = evidence_for(q, choice)
                    if (
                        not isinstance(evidence, tuple)
                        or len(evidence) != 1
                        or evidence[0]["scope"] != q.scope
                        or not evidence[0]["root"]
                    ):
                        raise ValueError("invalid original Shadow source presentation")
                    raw, receipt = answer(
                        q, evidence, f"shadow-reader/48/{phase}/{q.identity}/{arm}"
                    )
                    if (
                        not isinstance(raw, str) or not raw.strip()
                        or receipt["generator_identity"] != reader_identity
                        or receipt["generator_profile"] != reader_profile
                        or receipt["observable_query"] != asdict(q)
                        or receipt["delivered_evidence"] != list(evidence)
                        or receipt["canonical_request_digest"] != digest(
                            (reader_identity, reader_profile, asdict(q), evidence)
                        )
                        or type(receipt["actual_reader_execution"]) is not bool
                    ):
                        raise ValueError("Shadow Reader model/request binding failure")
                    item.update(
                        status="succeeded",
                        answer=raw,
                        receipt=receipt,
                    )
                except Exception as exc:
                    item.update(
                        status="failed", error_type=type(exc).__name__,
                        error=str(exc)[:1024],
                    )
                results.append(item)
    if len(results) != 32:
        raise ValueError("incomplete fixed 32-case Shadow Reader output census")
    return results



def _verified_reader_receipt(row):
    """Authenticate one sealed Reader request; labels never enter this check."""
    receipt = row.get("receipt")
    if not isinstance(receipt, dict):
        raise ValueError("missing original frozen Reader receipt")
    query = receipt.get("observable_query")
    evidence = receipt.get("delivered_evidence")
    if (
        not isinstance(query, dict)
        or query.get("identity") != row.get("question_id")
        or not isinstance(evidence, list)
        or len(evidence) > 1
        or any(not isinstance(item, dict) for item in evidence)
        or not isinstance(receipt.get("generator_identity"), str)
        or not receipt["generator_identity"]
        or not isinstance(receipt.get("generator_profile"), str)
        or not receipt["generator_profile"]
        or receipt.get("question_digest") != digest(query)
    ):
        raise ValueError("original Reader question or model identity drift")
    for key in ("canonical_request_digest", "input_ids_digest", "generated_ids_digest"):
        value = receipt.get(key)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("missing or malformed original Reader token/request seal")
    canonical = digest((
        receipt["generator_identity"],
        receipt["generator_profile"],
        query,
        tuple(evidence),
    ))
    if receipt["canonical_request_digest"] != canonical:
        raise ValueError("Reader canonical request does not bind actual evidence")
    return receipt

def review_final_shadow_reader(records, frozen_attempts, targets, diagnose):
    """Score only AFTER all raw Reader outcomes are sealed; no model calls."""
    if len(records) != 32 or not callable(diagnose):
        raise ValueError("missing complete post-policy Shadow Reader census")
    expected = {(phase, arm) for phase in TEST_PHASES for arm in ARMS}
    groups, matched = defaultdict(list), set()
    frozen = {
        (item["phase"], item["question_id"]): item for item in frozen_attempts
        if item.get("stage") == 48 and item.get("arm") == "frozen_rerank"
        and item.get("phase") in TEST_PHASES
    }
    if len(frozen) != 16 or set(targets) != {qid for _, qid in frozen}:
        raise ValueError("unbound original frozen Reader answers or targets")
    for r in records:
        key = (r["phase"], r["question_id"], r["arm"])
        if key in matched or r["stage"] != 48 or r["phase"] not in TEST_PHASES or r["arm"] not in ARMS:
            raise ValueError("duplicate or out-of-register Shadow Reader row")
        matched.add(key)
        base = frozen.get((r["phase"], r["question_id"]))
        if (
            base is None
            or base.get("family") != r["source_family"]
            or r["status"] not in ("succeeded", "failed", "unavailable")
            or r["native_target_passed_to_generator"] is not False
        ):
            raise ValueError("Shadow Reader answer altered original source or label scope")
        same_request = same_input = None
        if r["status"] == "succeeded":
            receipt = _verified_reader_receipt(r)
            if base["status"] == "succeeded":
                orig = _verified_reader_receipt(base)
                if (
                    orig["generator_identity"] != receipt["generator_identity"]
                    or orig["generator_profile"] != receipt["generator_profile"]
                    or orig["observable_query"] != receipt["observable_query"]
                    or r.get("frozen_selected") != base.get("selected")
                    or type(r.get("changed_frozen_selected_source")) is not bool
                    or r["changed_frozen_selected_source"] != (
                        r.get("shadow_selected") != base.get("selected")
                    )
                ):
                    raise ValueError("matched original and Shadow Reader profile/selection drift")
                if (
                    r["shadow_selected"] == base["selected"]
                    and orig["delivered_evidence"] != receipt["delivered_evidence"]
                ):
                    raise ValueError("unchanged source selection changed Reader evidence")
                same_request = (
                    orig["canonical_request_digest"] == receipt["canonical_request_digest"]
                )
                same_input = orig["input_ids_digest"] == receipt["input_ids_digest"]
                if same_request and not same_input:
                    raise ValueError("identical Reader request changed prompt tokens")
                if same_input and (
                    orig["generated_ids_digest"] != receipt["generated_ids_digest"]
                    or base["answer"] != r["answer"]
                ):
                    raise ValueError("identical Reader input cannot create a learning gain")
        can_compare = base["status"] == r["status"] == "succeeded"
        original_f1 = new_f1 = None
        if can_compare:
            original_f1, new_f1 = (
                diagnose(base["answer"], targets[r["question_id"]]),
                diagnose(r["answer"], targets[r["question_id"]]),
            )
            if any(
                v is not None and (
                    type(v) not in (int, float) or not math.isfinite(v)
                    or not 0 <= v <= 1
                ) for v in (original_f1, new_f1)
            ):
                raise ValueError("invalid frozen-matched token-F1 diagnostic")
        delta = (
            new_f1 - original_f1
            if original_f1 is not None and new_f1 is not None else None
        )
        result = dict(
            stage=48, phase=r["phase"], question_id=r["question_id"], arm=r["arm"],
            source_family=r["source_family"], status=r["status"],
            frozen_reader_succeeded=base["status"] == "succeeded",
            shadow_reader_succeeded=r["status"] == "succeeded",
            matched_reader_f1_delta=delta,
            source_changed=r.get("changed_frozen_selected_source"),
            identical_canonical_reader_request=same_request,
            identical_reader_token_input=same_input,
            changed_source_but_identical_reader_input=(
                r.get("changed_frozen_selected_source") is True
                and same_input is True
            ),
            answer_bytes_changed=(
                base["answer"] != r["answer"] if can_compare else None
            ),
            structural_evidence_markers=(
                len(re.findall(r"\[E\d+\]", r["answer"]))
                if r["status"] == "succeeded" else None
            ),
            semantic_citation_precision=None,
        )
        groups[(r["phase"], r["arm"])].append(result)
    if set(groups) != expected or any(len(groups[k]) != 8 for k in expected):
        raise ValueError("incomplete 8-per-cell/arm final Shadow Reader census")
    summary = {}
    for key, rows in sorted(groups.items()):
        deltas = [r["matched_reader_f1_delta"] for r in rows
                  if r["matched_reader_f1_delta"] is not None]
        changed = [r for r in rows if r["source_changed"] is True]
        changed_deltas = [r["matched_reader_f1_delta"] for r in changed
                          if r["matched_reader_f1_delta"] is not None]
        changed_unscored = len(changed) - len(changed_deltas)
        missing = 8 - len(deltas)
        summary["/".join(key)] = dict(
            attempted=8,
            shadow_successes=sum(r["shadow_reader_succeeded"] for r in rows),
            frozen_reader_failures=sum(not r["frozen_reader_succeeded"] for r in rows),
            source_changed=sum(r["source_changed"] is True for r in rows),
            identical_request_pairs=sum(
                r["identical_canonical_reader_request"] is True for r in rows
            ),
            identical_input_pairs=sum(
                r["identical_reader_token_input"] is True for r in rows
            ),
            source_flips_without_changed_reader_input=sum(
                r["changed_source_but_identical_reader_input"] for r in rows
            ),
            scored_matched_answers=len(deltas),
            missing_failed_or_unscorable=missing,
            mean_paired_diagnostic_f1_delta=(
                math.fsum(deltas)/len(deltas) if deltas else None
            ),
            original_8_planned_f1_delta_bounds=[
                (math.fsum(deltas)-missing)/8,
                (math.fsum(deltas)+missing)/8,
            ],
            changed_source_scored=len(changed_deltas),
            changed_source_reader_unscored=changed_unscored,
            changed_source_all_observed_f1_delta_bounds=(
                [
                    (math.fsum(changed_deltas) - changed_unscored) / len(changed),
                    (math.fsum(changed_deltas) + changed_unscored) / len(changed),
                ] if changed else None
            ),
            changed_source_conditional_mean_f1_delta=(
                math.fsum(changed_deltas)/len(changed_deltas)
                if changed_deltas else None
            ),
            actual_original_reader_answer_differences=sum(
                r["answer_bytes_changed"] is True for r in rows
            ),
            independent_source_entailment_judged=False,
            semantic_citation_precision=None,
        )
    return dict(
        schema="hepta.stem-final-shadow-vs-frozen-reader.v1",
        final_checkpoint=48, planned_reader_controls=len(records),
        predeclared_test_and_transfer_only=True,
        postpolicy_answer_targets_only=True,
        same_fixed_reader_weights_prompt_generation=True,
        original_576_policy_answers_unchanged=True,
        native_document_support_not_semantic_citation=True,
        independent_semantic_citation_precision=None,
        independent_prospective_generalization=False,
        per_phase_arm=summary,
        results=[r for phase in TEST_PHASES for arm in ARMS
                 for r in groups[(phase,arm)]],
        production_accepted=False,
    )
