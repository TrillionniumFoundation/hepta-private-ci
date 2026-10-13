"""Label-assisted, post-policy *diagnostic* Reader substitution.

Only test/transfer cases in which a native-supported source is already in
the fixed, strict-as-of frozen candidate pool but frozen top-1 missed it may
receive another one-window Reader request. Labels never enter training,
retrieval, Head selection, calibration or the original 576 policy calls.

This is NOT a learned selection policy, a sufficient-evidence oracle, or
independently reviewed passage entailment. Preserve all 16 case dispositions.
"""

from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import math
import re

from native import digest
from sessions import source_id
from stem_cell_time import source_not_after_question

PHASES = ("test", "transfer")
REASONS = (
    "native_unanswerable",
    "native_support_unresolved",
    "source_pool_unavailable",
    "native_support_absent_from_original_pool",
    "native_support_already_selected",
    "frozen_reader_failed",
    "eligible_native_support_top1_miss",
)


def _baseline_pairs(questions, frozen_attempts):
    expected = {
        (phase, q.identity): q
        for phase in PHASES for q in questions[phase]
    }
    if (
        set(questions) != set(PHASES)
        or any(len(questions[p]) != 8 for p in PHASES)
        or len(expected) != 16
        or len({q.identity for p in PHASES for q in questions[p]}) != 16
    ):
        raise ValueError("exactly 16 registered test/transfer questions required")
    found = {}
    for row in frozen_attempts:
        # The native runner passes the ALREADY SEALED full 576-row six-arm
        # journal. Earlier checkpoints and legitimate select/retention phases
        # are not unregistered post-policy Reader counterfactuals.
        if (
            row["stage"] != 48
            or row["arm"] != "frozen_rerank"
            or row["phase"] not in PHASES
        ):
            continue
        key = row["phase"], row["question_id"]
        if key not in expected or key in found:
            raise ValueError("unregistered or duplicated frozen Reader comparator")
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unknown baseline Reader status")
        found[key] = row
    if set(found) != set(expected):
        raise ValueError("missing frozen Reader baseline question")
    return expected, found


def prepare_native_window_interventions(
    questions, frozen_attempts, pools, frozen_features, targets, *,
    selected_window,
):
    """Choose a fixed retrospective diagnostic from *native source IDs only*.

    Deterministic tie policy: highest ORIGINAL frozen Encoder logit among
    native-supported candidates, lexical candidate ID if tied.
    """
    if not callable(selected_window):
        raise ValueError("original source-bound window projection required")
    expected, frozen = _baseline_pairs(questions, frozen_attempts)
    if set(targets) != {q.identity for q in expected.values()}:
        raise ValueError("only the original 16 target metadata objects admitted")
    result = []
    for (phase, qid), q in expected.items():
        row, target = frozen[(phase, qid)], targets[qid]
        pool, feature = pools.get(qid), frozen_features.get(qid)
        base = dict(
            schema="hepta.stem-labelled-window-reader-diagnostic.v1",
            phase=phase, question_id=qid,
            original_question_sha256=digest(asdict(q)),
            original_policy_status=row["status"],
            native_document_support_is_not_passage_entailment=True,
            intervention_is_privileged_postpolicy=True,
            labels_used_during_original_policy=False,
            gold_answer_passed_to_reader=False,
            independent_reviewer_certified=False,
            production_accepted=False,
        )
        if type(target.unanswerable) is not bool:
            raise ValueError("unknown native answerability")
        if target.unanswerable:
            reason = "native_unanswerable"
        elif not target.evidence or target.unresolved_evidence:
            reason = "native_support_unresolved"
        elif pool is None or feature is None:
            reason = "source_pool_unavailable"
        else:
            names = tuple(w.identity() for w in pool.windows)
            scores = feature.frozen_scores.tolist()
            if (
                feature.question_id != qid
                or feature.pool_digest != pool.seal()
                or feature.candidate_ids != names
                or len(scores) != len(names)
                or len(set(names)) != len(names)
                or len(names) > 64
                or not isinstance(row.get("pool_digest"), str)
                or row["pool_digest"] != pool.seal()
                or any(w.scope != q.scope for w in pool.windows)
                or any(not math.isfinite(float(v)) for v in scores)
            ):
                raise ValueError("original candidate pool and frozen logits mismatch")
            candidates = {
                source_id(value) for value in target.evidence
            }
            support = [
                i for i, window in enumerate(pool.windows)
                if source_id(window.source_id) in candidates
            ]
            chosen = row.get("selected")
            if chosen is not None and (
                type(chosen) is not int or not 0 <= chosen < len(names)
            ):
                raise ValueError("baseline top1 not bound to original pool")
            expected_frozen = (
                min(range(len(names)), key=lambda i: (-float(scores[i]), names[i]))
                if names else None
            )
            if chosen is not None and chosen != expected_frozen:
                raise ValueError("baseline frozen score rank differs from recorded top1")
            if row["status"] == "succeeded" and chosen != expected_frozen:
                raise ValueError("successful original forced-top1 selector missing")
            base.update(
                candidate_count=len(names),
                weak_supported_window_count=len(support),
                original_frozen_top1=chosen,
                original_pool_sha256=pool.seal(),
            )
            if not support:
                reason = "native_support_absent_from_original_pool"
            elif chosen in support:
                reason = "native_support_already_selected"
            elif row["status"] != "succeeded":
                reason = "frozen_reader_failed"
            else:
                reason = "eligible_native_support_top1_miss"
                rank = min(
                    support, key=lambda i: (-float(scores[i]), names[i])
                )
                evidence = selected_window(q, pool, feature, rank, set())
                if (
                    not isinstance(evidence, (tuple, list))
                    or len(evidence) != 1
                    or evidence[0]["scope"] != q.scope
                    or evidence[0]["label"] != "E1"
                    or not source_not_after_question(
                        evidence[0]["observed_at"], q.observed_at
                    )
                ):
                    raise ValueError("unbound native weak-support Reader source")
                reader = row.get("receipt")
                if not isinstance(reader, dict) or not reader.get("generator_identity") or not reader.get("generator_profile") or reader.get("observable_query") != asdict(q):
                    raise ValueError("original Reader identity or query not available")
                base.update(
                    diagnostic_selection_index=rank,
                    candidate_window_sha256=names[rank],
                    diagnostic_evidence=evidence,
                    original_reader_identity=reader["generator_identity"],
                    original_reader_profile=reader["generator_profile"],
                    original_answer_sha256=sha256(
                        row["answer"].encode("utf-8", "strict")
                    ).hexdigest(),
                    original_answer=row["answer"],
                )
        base["disposition"] = reason
        result.append(base)
    if len(result) != 16:
        raise ValueError("post-policy intervention lost registered question")
    return result


def generate_native_window_interventions(prepared, questions, generate):
    """Run only predeclared eligible cases with one unchanged Reader request."""
    if len(prepared) != 16 or not callable(generate):
        raise ValueError("complete labelled Reader intervention required")
    by_id = {(p, q.identity): q for p in PHASES for q in questions[p]}
    if len(by_id) != 16:
        raise ValueError("registered question duplicate")
    seen, output = set(), []
    for row in prepared:
        key = row["phase"], row["question_id"]
        if key not in by_id or key in seen or row["disposition"] not in REASONS:
            raise ValueError("invalid or duplicate Reader diagnostic disposition")
        seen.add(key)
        item = {k: v for k, v in row.items() if k not in
                ("diagnostic_evidence", "original_answer")}
        if row["disposition"] == "eligible_native_support_top1_miss":
            # Preserve the EXACT attempted request even if Reader raises before
            # it can return a receipt. No post-hoc evidence substitution.
            item["intended_reader_evidence"] = list(row["diagnostic_evidence"])
            item["intended_canonical_request_digest"] = digest((
                row["original_reader_identity"], row["original_reader_profile"],
                asdict(by_id[key]), row["diagnostic_evidence"],
            ))
        item["status"] = "not_applicable"
        if row["disposition"] == "eligible_native_support_top1_miss":
            try:
                q, evidence = by_id[key], row["diagnostic_evidence"]
                raw, receipt = generate(
                    q, evidence, f"native-weak-window/{row['phase']}/{q.identity}"
                )
                if (
                    not isinstance(raw, str) or not raw.strip()
                    or not isinstance(receipt, dict)
                    or receipt.get("generator_identity") != row["original_reader_identity"]
                    or receipt.get("generator_profile") != row["original_reader_profile"]
                    or receipt.get("observable_query") != asdict(q)
                    or receipt.get("delivered_evidence") != list(evidence)
                    or receipt.get("actual_reader_execution") is not True
                    or receipt.get("canonical_request_digest") != digest((
                        row["original_reader_identity"], row["original_reader_profile"],
                        asdict(q), evidence,
                    ))
                ):
                    raise ValueError("Reader model/prompt/source request detached")
                markers = re.findall(r"\[E[1-9][0-9]*\]", raw)
                delivered_labels = {e["label"] for e in evidence}
                item.update(
                    status="succeeded", answer=raw, receipt=receipt,
                    original_answer=row["original_answer"],
                    emitted_citation_markers=len(markers),
                    markers_with_original_delivered_label=sum(
                        marker[1:-1] in delivered_labels for marker in markers
                    ),
                    citation_entailment_independently_verified=False,
                )
            except Exception as exc:
                item.update(
                    status="failed", error_type=type(exc).__name__,
                    error=str(exc)[:1024],
                )
        output.append(item)
    if seen != set(by_id):
        raise ValueError("missing Reader intervention cases")
    return output


def review_native_window_interventions(records, targets, diagnose):
    """Score only after all targeted Reader calls; no target answer in prompts."""
    if len(records) != 16 or not callable(diagnose):
        raise ValueError("complete post-call native Reader review required")
    seen, cases = set(), []
    for row in records:
        key = row["phase"], row["question_id"]
        if (row["phase"] not in PHASES or key in seen
                or row["question_id"] not in targets):
            raise ValueError("duplicated or unregistered diagnostic review")
        seen.add(key)
        planned = row["disposition"] == "eligible_native_support_top1_miss"
        if (planned and row["status"] not in ("succeeded", "failed")) or (
            not planned and row["status"] != "not_applicable"
        ):
            raise ValueError("lost or fabricated eligible Reader attempt")
        scored = dict(
            phase=row["phase"], question_id=row["question_id"],
            disposition=row["disposition"], status=row["status"],
            paired_f1_delta=None, semantic_citation_precision=None,
            emitted_citation_markers=row.get("emitted_citation_markers"),
            markers_with_original_delivered_label=row.get(
                "markers_with_original_delivered_label"
            ),
        )
        if row["status"] == "succeeded":
            original = diagnose(row["original_answer"], targets[row["question_id"]])
            after = diagnose(row["answer"], targets[row["question_id"]])
            if original is not None and after is not None:
                if any(type(x) not in (int, float) or not math.isfinite(x)
                       or not 0 <= x <= 1 for x in (original, after)):
                    raise ValueError("invalid Reader diagnostic token-F1")
                scored["paired_f1_delta"] = after - original
        cases.append(scored)
    if len(seen) != 16:
        raise ValueError("incomplete 16-question Reader intervention")
    counts = Counter(row["disposition"] for row in cases)
    eligible = counts["eligible_native_support_top1_miss"]
    executed = [r for r in cases
                if r["disposition"] == "eligible_native_support_top1_miss"]
    observed = [r["paired_f1_delta"] for r in executed
                if r["paired_f1_delta"] is not None]
    unknown = eligible - len(observed)
    sum_delta = math.fsum(observed)
    by_phase = {}
    for phase in PHASES:
        subset = [c for c in cases if c["phase"] == phase]
        eligible_phase = [
            c for c in subset if c["disposition"] == "eligible_native_support_top1_miss"
        ]
        values = [
            c["paired_f1_delta"] for c in eligible_phase
            if c["paired_f1_delta"] is not None
        ]
        missing = len(eligible_phase) - len(values)
        total = math.fsum(values)
        by_phase[phase] = dict(
            original_questions=len(subset),
            eligible_substitutions=len(eligible_phase),
            executed_and_scored=len(values),
            failed_or_unscored=missing,
            mean_paired_f1_delta=(total / len(values) if values else None),
            all_eligible_delta_bounds=(
                [(total - missing) / len(eligible_phase),
                 (total + missing) / len(eligible_phase)]
                if eligible_phase else None
            ),
            independence_not_established=True,
        )
        if len(subset) != 8:
            raise ValueError("test/transfer phase denominator drift")
    return dict(
        schema="hepta.stem-labelled-window-reader-report.v1",
        original_test_transfer_questions=16,
        disposition_counts=dict(counts),
        per_phase=by_phase,
        eligible_postpolicy_labelled_source_substitutions=eligible,
        actual_reader_successes=sum(r["status"] == "succeeded" for r in executed),
        actual_reader_failures=sum(r["status"] == "failed" for r in executed),
        paired_answers_scored=len(observed),
        succeeded_reader_emitted_citation_markers=sum(
            row["emitted_citation_markers"] or 0 for row in executed
        ),
        markers_bound_to_one_original_delivered_window=sum(
            row["markers_with_original_delivered_label"] or 0
            for row in executed
        ),
        structural_marker_binding_is_not_semantic_entailment=True,
        failed_requests_retain_intended_evidence_and_request_digest=True,
        conditional_paired_reader_f1_delta=(
            sum_delta / len(observed) if observed else None
        ),
        all_eligible_score_bounds=(
            [(sum_delta - unknown) / eligible, (sum_delta + unknown) / eligible]
            if eligible else None
        ),
        cases=cases,
        gold_source_labels_used_only_after_original_policy=True,
        reference_labelled_source_not_semantically_reviewed=True,
        production_policy_unchanged=True,
        independent_sufficient_evidence_oracle=False,
        semantic_citation_precision=None,
        production_accepted=False,
    )
