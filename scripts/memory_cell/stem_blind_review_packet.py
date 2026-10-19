"""Blind, unadjudicated source sufficiency/answer support handoff.

Preserves the exactly 32 original final-checkpoint questions and their two
frozen Reader conditions. Reviewers see no benchmark target/gold labels, arm
names, native support verdicts, training records, or privileged answer-literal
Oracle. This is a worklist, NOT an independent review or an approval.
"""

from collections import Counter
import hashlib
import re

from native import digest
from stem_cell_time import source_not_after_question

PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
MARKERS = re.compile(r"\[E[0-9]+\]")


def _verify_reader(row, qid, *, require_empty=False):
    if row["status"] not in ("succeeded", "failed"):
        raise ValueError("invalid original Reader execution state")
    if row["status"] == "failed":
        if any(name in row for name in ("answer", "receipt")):
            raise ValueError("failed Reader case cannot supply forged raw answer")
        return None
    receipt = row.get("receipt")
    answer = row.get("answer")
    if (
        not isinstance(receipt, dict)
        or not isinstance(answer, str)
        or not answer.strip()
    ):
        raise ValueError("missing unaltered original Reader answer/receipt")
    query = receipt.get("observable_query")
    if (
        not isinstance(query, dict)
        or set(query) != {"identity", "family", "scope", "content", "observed_at"}
        or query.get("identity") != qid
        or any(not isinstance(v, str) or not v for v in query.values())
        or not isinstance(receipt.get("generator_identity"), str)
        or not receipt["generator_identity"]
        or not isinstance(receipt.get("generator_profile"), str)
        or not receipt["generator_profile"]
    ):
        raise ValueError("unbound Reader/query identity in review worklist")
    evidence = receipt.get("delivered_evidence")
    if (
        not isinstance(evidence, list)
        or len(evidence) > 1
        or (require_empty and evidence)
    ):
        raise ValueError("zero-evidence Reader received nonempty evidence")
    labels = []
    safe_sources = []
    for item in evidence:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("label"), str)
            or not re.fullmatch(r"E[1-9][0-9]*", item["label"])
            or not isinstance(item.get("excerpt"), str)
            or not item["excerpt"]
            or not isinstance(item.get("scope"), str)
            or item["scope"] != query["scope"]
            or not isinstance(item.get("observed_at"), str)
            or not source_not_after_question(item["observed_at"], query["observed_at"])
            or not isinstance(item.get("root"), str)
            or not item["root"]
        ):
            raise ValueError("untrusted or future original evidence reference")
        labels.append(item["label"])
        safe_sources.append(
            dict(
                label=item["label"],
                source_observed_at=item["observed_at"],
                excerpt=item["excerpt"],
            )
        )
    if len(set(labels)) != len(labels):
        raise ValueError("duplicated original Reader source label")
    canonical = digest(
        (
            receipt["generator_identity"],
            receipt["generator_profile"],
            query,
            evidence,
        )
    )
    if receipt.get("canonical_request_digest") != canonical:
        raise ValueError("original Reader request not tied to evidence bytes")
    markers = MARKERS.findall(answer)
    unbound = sum(m[1:-1] not in labels for m in markers)
    return dict(
        query=query,
        answer=answer,
        evidence=safe_sources,
        evidence_count=len(evidence),
        request_digest=canonical,
        source_payload_digest=digest(evidence),
        raw_answer_digest=hashlib.sha256(answer.encode("utf-8", "strict")).hexdigest(),
        generator_identity=receipt["generator_identity"],
        generator_profile=receipt["generator_profile"],
        citation_markers=markers,
        unbound_citation_markers=unbound,
    )


def make_blind_review_packet(plan, predictions, zero_rows):
    """Return public-to-reviewer packet plus withheld mapping; never read labels."""
    questions = plan["questions"]
    if (
        plan.get("schema") != "hepta.stem-cell.native-development.v1"
        or not isinstance(plan.get("source_commit"), str)
        or not re.fullmatch(r"[a-f0-9]{40}", plan["source_commit"])
        or tuple(plan["arms"]) != ARMS
        or tuple(plan["curriculum_attempted_examples"]) != STAGES
        or len(questions.get("train", ())) != 48
        or any(len(questions.get(p, ())) != 8 for p in PHASES)
    ):
        raise ValueError("pinned native experiment registration missing")
    registered = [q for p in ("train", *PHASES) for q in questions[p]]
    if len(set(registered)) != 80:
        raise ValueError("duplicate preregistered native questions")
    expected = {
        (stage, phase, qid, arm)
        for stage in STAGES
        for phase in PHASES
        for qid in questions[phase]
        for arm in ARMS
    }
    seen = {}
    for row in predictions:
        key = row["stage"], row["phase"], row["question_id"], row["arm"]
        if key not in expected or key in seen:
            raise ValueError("duplicate or extra original policy answer")
        seen[key] = row
    if len(predictions) != 576 or set(seen) != expected:
        raise ValueError("incomplete original 576-policy attempt denominator")
    empty = {}
    for row in zero_rows:
        key = row["phase"], row["question_id"]
        if (
            row["phase"] not in PHASES
            or row["question_id"] not in questions[row["phase"]]
            or key in empty
        ):
            raise ValueError("duplicate or unregistered zero-evidence question")
        empty[key] = row
    if len(zero_rows) != 32 or len(empty) != 32:
        raise ValueError("32 original no-evidence Reader records required")
    packet, mapping = [], []
    status_counts = Counter()
    for phase in PHASES:
        for qid in questions[phase]:
            frozen_row = seen[(48, phase, qid, "frozen_rerank")]
            zero_row = empty[(phase, qid)]
            expected_family = plan["question_families"][qid]
            if (
                not isinstance(expected_family, str)
                or not expected_family
                or frozen_row.get("family") != expected_family
                or zero_row.get("family") != expected_family
            ):
                raise ValueError("unregistered source-family in paired review inputs")
            source = _verify_reader(frozen_row, qid)
            if zero_row.get("evidence_count") != 0:
                raise ValueError("empty Reader label changed into supplied source")
            blank = _verify_reader(zero_row, qid, require_empty=True)
            if source is not None and "selected" in frozen_row:
                selected = frozen_row["selected"]
                if (selected is None and source["evidence_count"] != 0) or (
                    selected is not None
                    and (
                        type(selected) is not int
                        or selected < 0
                        or source["evidence_count"] != 1
                    )
                ):
                    raise ValueError(
                        "frozen selected source and delivered evidence drift"
                    )
            identities = {
                (view["generator_identity"], view["generator_profile"])
                for view in (source, blank)
                if view is not None
            }
            if len(identities) > 1:
                raise ValueError("different model or prompt in matched review inputs")
            if (
                source is not None
                and blank is not None
                and source["query"] != blank["query"]
            ):
                raise ValueError(
                    "different original question in matched Reader controls"
                )
            query = (
                source["query"]
                if source is not None
                else (blank["query"] if blank is not None else None)
            )
            case_id = digest(("stem-blind-review-v1", plan["source_commit"], qid))
            order = sorted(
                ("fixed", "empty"),
                key=lambda role: digest(("stem-blind-review-slot", case_id, role)),
            )
            conditions, provenance = [], {}
            for index, role in enumerate(order):
                view = source if role == "fixed" else blank
                status = "unreviewable-reader-failure" if view is None else "unreviewed"
                status_counts[status] += 1
                slot = "AB"[index]
                conditions.append(
                    dict(
                        slot=slot,
                        original_reader_status=(
                            "failed" if view is None else "succeeded"
                        ),
                        answer=None if view is None else view["answer"],
                        delivered_evidence=[] if view is None else view["evidence"],
                        original_citation_markers=[]
                        if view is None
                        else view["citation_markers"],
                        structurally_unbound_markers=(
                            None if view is None else view["unbound_citation_markers"]
                        ),
                        reviewer_verdict=None,
                        independent_semantic_review_completed=False,
                    )
                )
                provenance[slot] = dict(
                    role=role,
                    raw_request_digest=None if view is None else view["request_digest"],
                    evidence_digest=None
                    if view is None
                    else view["source_payload_digest"],
                    answer_digest=None if view is None else view["raw_answer_digest"],
                )
            packet.append(
                dict(
                    schema="hepta.stem-blind-semantic-worklist.v1",
                    case_id=case_id,
                    question=None if query is None else query["content"],
                    question_observed_at=None
                    if query is None
                    else query["observed_at"],
                    conditions=conditions,
                    answer_key_or_gold_annotations_included=False,
                    privileged_oracle_evidence_included=False,
                    origin_arm_names_included=False,
                    source_sufficiency_review_pending=True,
                    independent_citation_entailment_pending=True,
                )
            )
            requests = [v["request_digest"] for v in (source, blank) if v is not None]
            mapping.append(
                dict(
                    case_id=case_id,
                    native_phase=phase,
                    original_question_id=qid,
                    source_family=plan["question_families"][qid],
                    opaque_slots=provenance,
                    identical_request_if_both_succeeded=(
                        source["request_digest"] == blank["request_digest"]
                        if source is not None and blank is not None
                        else None
                    ),
                    distinct_original_requests=len(set(requests)),
                )
            )
    if len(packet) != 32 or len(mapping) != 32:
        raise ValueError("lost native reviewer questionnaire cases")
    return dict(
        schema="hepta.stem-blind-review-packet.v1",
        original_source_commit=plan["source_commit"],
        original_cases=32,
        reader_conditions=64,
        original_raw_reader_results_retained=True,
        status_counts=dict(status_counts),
        reviewer_packets=packet,
        no_gold_answers_read=True,
        semantic_citation_precision=None,
        independent_review_certified=False,
        production_accepted=False,
    ), dict(
        schema="hepta.stem-blind-review-provenance.v1",
        original_source_commit=plan["source_commit"],
        original_cases=32,
        blinded_case_mapping=mapping,
        no_review_verdicts_entered=True,
        independent_reviewer_identity_verified=False,
        independent_semantic_sufficiency_certified=False,
        production_accepted=False,
    )
