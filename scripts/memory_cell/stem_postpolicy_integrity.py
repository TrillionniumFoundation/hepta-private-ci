"""Independent post-policy source/Reader score integrity audit.

Check all original 576 unmodified prediction records against post-hoc scores,
native weak source labels and the SEALED candidate windows. Run only AFTER
all policy answers exist. This checks receipts and arithmetic, not semantic
entailment, prospective generalization or production authorization.
"""

from collections import Counter
from dataclasses import asdict
import math
import re

from native import digest
from sessions import source_id
from stem_cell_time import source_not_after_question


ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")
PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)
ADDED = frozenset((
    "source_choice_correct", "diagnostic_answer_f1", "citation_structure",
))


def _diagnostic_f1(raw, target):
    # Independently reproduce the *published token overlap* diagnostic only.
    # This is deliberately not an answer correctness/semantic citation judge.
    if target.answer is None:
        return None
    def tokens(value):
        return re.findall(
            r"\w+", re.sub(r"\b(a|an|the)\b", " ", value.casefold())
        )
    answer, reference = Counter(tokens(raw)), Counter(tokens(target.answer))
    overlap = sum((answer & reference).values())
    na, nb = sum(answer.values()), sum(reference.values())
    return 2 * overlap / (na + nb) if na and nb else float(answer == reference)


def _expected_source(target, pool, row):
    if "selected" not in row:
        return 0
    if target.unresolved_evidence:
        return None
    if target.unanswerable:
        return int(row["selected"] is None)
    if not target.evidence:
        return None
    if pool is None:
        raise ValueError("observed selection missing original candidate pool")
    supported = {source_id(s) for s in target.evidence}
    selected = row["selected"]
    return int(
        selected is not None
        and source_id(pool.windows[selected].source_id) in supported
    )


def _expected_evidence(pool, selection):
    if selection is None:
        return []
    window = pool.windows[selection]
    return [dict(
        label="E1", id=window.identity(), original_id=window.source_id,
        root=window.root, scope=window.scope, excerpt=window.text,
        source_start=window.start, source_end=window.end,
        observed_at=window.observed_at,
        inspected_sha256=window.inspected_sha256,
    )]


def audit_policy_scoring(plan, raw, scored, pools, questions, targets):
    """Reject label inflation, altered raw answers, source or citation receipts.

    The scorer is independently verified against immutable raw records and
    original source-window identities; only post-policy annotations are read.
    """
    expected_questions = {
        q for phase in PHASES for q in plan["questions"][phase]
    }
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES for phase in PHASES
        for qid in plan["questions"][phase] for arm in ARMS
    }
    if (
        tuple(plan["arms"]) != ARMS
        or tuple(plan["curriculum_attempted_examples"]) != STAGES
        or any(len(plan["questions"][phase]) != 8 for phase in PHASES)
        or len(expected_questions) != 32
        or set(questions) != expected_questions
        or set(targets) != expected_questions
        or not set(pools).issubset(expected_questions)
        or len(raw) != 576 or len(scored) != 576
    ):
        raise ValueError("unregistered or incomplete 576-case post-policy audit")
    indexed, annotated = {}, {}
    for source, destination in ((raw, indexed), (scored, annotated)):
        for row in source:
            key = row["stage"], row["phase"], row["question_id"], row["arm"]
            if key not in expected or key in destination:
                raise ValueError("missing or duplicate originally registered policy")
            destination[key] = row
    if set(indexed) != expected or set(annotated) != expected:
        raise ValueError("missing or unexpected policy identifiers")

    census = Counter()
    reader_pin = None
    canonical_output_pins = {}
    for key in sorted(expected):
        original, reviewed = indexed[key], annotated[key]
        if (
            not ADDED.isdisjoint(original)
            or set(reviewed) != set(original) | ADDED
            or {k: v for k, v in reviewed.items() if k not in ADDED} != original
            or original.get("family") != plan["question_families"][key[2]]
        ):
            raise ValueError("raw policy answer, family or receipt rewritten by scoring")
        qid = key[2]
        q, target, pool = questions[qid], targets[qid], pools.get(qid)
        if q.identity != qid or not isinstance(target.unanswerable, bool):
            raise ValueError("target/question identity or answerability malformed")
        observed = "selected" in original
        if observed:
            chosen = original["selected"]
            if pool is None or (
                chosen is not None and (
                    type(chosen) is not int
                    or not 0 <= chosen < len(pool.windows)
                )
            ) or (chosen is None and len(pool.windows) > 0):
                raise ValueError("candidate selection outside original forced top-1 pool")
            if original.get("pool_digest") != pool.seal():
                raise ValueError("selected candidate's pool seal changed")
        elif original["status"] == "succeeded":
            raise ValueError("successful Reader without a selected-or-empty decision")
        if pool is not None:
            for window in pool.windows:
                if window.scope != q.scope or not source_not_after_question(
                    window.observed_at, q.observed_at
                ):
                    raise ValueError("future or cross-scope source reached paired Encoder")
        predicted = _expected_source(target, pool, original)
        claimed_source = reviewed["source_choice_correct"]
        if (
            (predicted is None and claimed_source is not None)
            or (
                predicted is not None
                and (type(claimed_source) is not int or claimed_source != predicted)
            )
        ):
            raise ValueError("native source correctness detached from actual selection")
        if original["status"] == "succeeded":
            if not isinstance(original.get("answer"), str) or not original["answer"].strip():
                raise ValueError("successful raw Reader answer missing")
            receipt = original.get("receipt")
            if not isinstance(receipt, dict) or (
                receipt.get("delivered_evidence") !=
                _expected_evidence(pool, original["selected"])
            ) or receipt.get("observable_query") != asdict(q):
                raise ValueError("Reader evidence or original question changed")
            if receipt.get("canonical_request_digest") != digest((
                receipt.get("generator_identity"), receipt.get("generator_profile"),
                asdict(q), receipt["delivered_evidence"]
            )):
                raise ValueError("original Reader request pin invalid")
            identity = (
                receipt.get("generator_identity"),
                receipt.get("generator_profile"),
            )
            if (
                not all(isinstance(x, str) and bool(x) for x in identity)
                or (reader_pin is not None and identity != reader_pin)
                or receipt.get("question_digest") != digest(asdict(q))
                or any(
                    not isinstance(receipt.get(field), str)
                    or re.fullmatch(r"[0-9a-f]{64}", receipt[field]) is None
                    for field in ("input_ids_digest", "generated_ids_digest")
                )
                or type(receipt.get("actual_reader_execution")) is not bool
                or not (
                    (receipt.get("reused_from") is None
                     and receipt["actual_reader_execution"] is True)
                    or (isinstance(receipt.get("reused_from"), str)
                        and bool(receipt["reused_from"])
                        and receipt["actual_reader_execution"] is False)
                )
            ):
                raise ValueError("Reader prompt, model, token or reuse identity drift")
            reader_pin = identity
            request_digest = receipt["canonical_request_digest"]
            canonical_output = (
                original["answer"],
                receipt["input_ids_digest"],
                receipt["generated_ids_digest"],
            )
            if (
                request_digest in canonical_output_pins
                and canonical_output_pins[request_digest] != canonical_output
            ):
                raise ValueError(
                    "identical frozen Reader request has inconsistent raw answer or tokens"
                )
            canonical_output_pins[request_digest] = canonical_output
            expected_f1 = _diagnostic_f1(original["answer"], target)
            if reviewed["diagnostic_answer_f1"] != expected_f1:
                raise ValueError("diagnostic answer F1 did not match raw answer")
            marks = re.findall(r"\[E(\d+)\]", original["answer"])
            labels = {e["label"] for e in receipt["delivered_evidence"]}
            delivered = sum("E" + marker in labels for marker in marks)
            citation = dict(
                markers=len(marks), delivered_markers=delivered,
                precision=None if not marks else delivered / len(marks),
                semantic_precision=None,
            )
            census["reader_success"] += 1
            census["delivered_markers"] += delivered
            census["total_citation_markers"] += len(marks)
        elif original["status"] == "failed":
            if "answer" in original or "receipt" in original:
                raise ValueError("failed Reader smuggled a success receipt")
            if reviewed["diagnostic_answer_f1"] != 0.0:
                raise ValueError("failed Reader answer misclassified as scored")
            citation = dict(
                markers=0, delivered_markers=0,
                precision=None, semantic_precision=None,
            )
            census["reader_failed"] += 1
        else:
            raise ValueError("unknown raw policy execution status")
        if reviewed["citation_structure"] != citation:
            raise ValueError("citation count or provenance detached from raw answer")
        census["source_scored" if predicted is not None else "source_unresolved"] += 1
        if target.unanswerable:
            census["native_unanswerable_attempts"] += 1
        if not observed:
            census["selector_not_observed"] += 1
    if census["reader_success"] + census["reader_failed"] != 576:
        raise ValueError("incomplete original policy outcome census")
    return dict(
        schema="hepta.stem-independent-postpolicy-integrity.v1",
        raw_policy_attempts=576, matched_scored_policy_attempts=576,
        original_policy_records_sha256=digest(raw),
        original_scored_policy_records_sha256=digest(scored),
        census=dict(census),
        same_original_source_candidate_pools=True,
        original_reader_requests_revalidated=True,
        unique_successful_canonical_reader_requests=len(canonical_output_pins),
        identical_reader_requests_yield_identical_answer_and_token_ids=True,
        same_frozen_reader_model_and_prompt_across_successful_arms=True,
        exact_question_token_and_cache_reuse_receipts_validated=True,
        future_source_window_admission_rechecked=True,
        postpolicy_only_native_target_observation=True,
        weak_document_support_not_semantic_entailment=True,
        independent_citation_quality_verified=False,
        benchmark_training_gain_qualified=False,
        production_accepted=False,
    )
