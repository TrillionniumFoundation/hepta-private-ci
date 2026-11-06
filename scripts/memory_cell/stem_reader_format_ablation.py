"""Frozen Reader JSON-versus-flat input diagnostic, after original Stem output.

Exactly the original pinned 32 stage-48 frozen-rerank question/evidence
requests are used. Change ONLY the user payload layout, not Reader weights,
system instruction, tokenizer, token ceiling, or decoding parameters.
No target labels are read before every new raw answer is durably written.
This is a research control, NOT a replacement for the original 576 decisions.
"""

from collections import defaultdict
from dataclasses import asdict
import math
import re

from native import Question, digest
from stem_cell_time import source_not_after_question

ARCHIVED_SOURCE = "1578121eb24cbb3d50fbe0ae27f2d48f870bb364"
ARCHIVED_TREE = "b40ee7f016d7830d59c45261a0dcf642800c2ec0"
ARCHIVED_ZIP_SHA256 = "65fe5e99c90a10dba916598dc2a83f164ef6275d7cb6c783aa6edbe3722d2563"
ARCHIVED_ARTIFACT = 11741082077
PHASES = ("select", "retention", "test", "transfer")
ARMS = (
    "frozen_rerank",
    "prototype",
    "linear",
    "gated",
    "lineage_lora_gated",
    "independent_lora_gated",
)
STAGES = (16, 32, 48)
FORMAT_ID = "hepta.stem-flat-evidence-user-format.v1"
CITATION = re.compile(r"\[E[0-9]+\]")


def fixed_frozen_cases(plan, policies):
    """Read only question and original Reader-receipt evidence, never targets."""
    if (
        plan.get("source_commit") != ARCHIVED_SOURCE
        or tuple(plan.get("arms", ())) != ARMS
        or tuple(plan.get("curriculum_attempted_examples", ())) != STAGES
        or set(plan.get("questions", {})) != {"train", *PHASES}
        or any(len(plan["questions"][p]) != 8 for p in PHASES)
    ):
        raise ValueError("original 32-question Reader preregistration drift")
    expected = {
        (s, p, q, arm)
        for s in STAGES
        for p in PHASES
        for q in plan["questions"][p]
        for arm in ARMS
    }
    found = {}
    for row in policies:
        key = (row["stage"], row["phase"], row["question_id"], row["arm"])
        if key not in expected or key in found:
            raise ValueError("unexpected or duplicate original Stem attempt")
        found[key] = row
    if len(found) != 576 or set(found) != expected:
        raise ValueError("incomplete original 576-row Stem policy census")
    cases = []
    for phase in PHASES:
        for qid in plan["questions"][phase]:
            row = found[(48, phase, qid, "frozen_rerank")]
            rec = row.get("receipt")
            if (
                row.get("status") != "succeeded"
                or not isinstance(rec, dict)
                or rec.get("generator_profile") is None
                or rec.get("generator_identity") is None
                or rec.get("production_accepted") is not False
                or not isinstance(rec.get("observable_query"), dict)
                or not isinstance(rec.get("delivered_evidence"), list)
                or len(rec["delivered_evidence"]) != 1
            ):
                raise ValueError("original matched frozen Reader evidence unavailable")
            q = Question(**rec["observable_query"])
            source = rec["delivered_evidence"][0]
            if (
                q.identity != qid
                or row.get("family") != plan["question_families"][qid]
                or rec.get("question_digest") != digest(asdict(q))
                or rec.get("canonical_request_digest")
                != digest(
                    (
                        rec["generator_identity"],
                        rec["generator_profile"],
                        asdict(q),
                        rec["delivered_evidence"],
                    )
                )
                or source.get("scope") != q.scope
                or source.get("label") != "E1"
                or source.get("id")
                != row.get("selection_geometry", {}).get("learned_top_id")
                or not isinstance(source.get("excerpt"), str)
                or not source["excerpt"].strip()
                or len(source["excerpt"].encode("utf-8")) > 8192
                or not source_not_after_question(source["observed_at"], q.observed_at)
            ):
                raise ValueError("unbound old Reader question/source payload")
            cases.append(
                dict(
                    phase=phase,
                    question_id=qid,
                    question=asdict(q),
                    delivered_evidence=rec["delivered_evidence"],
                    original_reader_identity=rec["generator_identity"],
                    original_reader_profile=rec["generator_profile"],
                    original_input_sha256=rec["input_ids_digest"],
                    original_generated_sha256=rec["generated_ids_digest"],
                    original_answer_sha256=digest(row["answer"]),
                    original_canonical_request_sha256=rec["canonical_request_digest"],
                    format_rewrite_only=True,
                )
            )
    if len(cases) != 32 or len({v["question_id"] for v in cases}) != 32:
        raise ValueError("registered frozen Reader controls not independent")
    return cases


def flat_user_message(query, sources):
    """One verbatim evidence excerpt in a fixed natural-language layout."""
    if (
        not isinstance(query, dict)
        or not isinstance(sources, list)
        or len(sources) != 1
        or set(("identity", "scope", "content", "observed_at")) - set(query)
    ):
        raise ValueError("unbound flattened prompt question")
    source = sources[0]
    if (
        source.get("label") != "E1"
        or source.get("scope") != query["scope"]
        or not isinstance(query["content"], str)
        or not isinstance(source.get("excerpt"), str)
        or not source["excerpt"].strip()
        or len(query["content"].encode("utf-8")) > 16384
        or len(source["excerpt"].encode("utf-8")) > 8192
        or not source_not_after_question(source["observed_at"], query["observed_at"])
    ):
        raise ValueError("invalid unchanged frozen Reader evidence")
    return (
        "Question:\n"
        + query["content"]
        + "\nQuestion time:\n"
        + query["observed_at"]
        + "\nEvidence [E1], observed at "
        + source["observed_at"]
        + ":\n"
        + source["excerpt"]
    )


def evaluate_flat_answers(cases, answers, original_scored, targets, diagnose):
    """Gold read only after all 32 raw flat-generation records exist."""
    cases_by_id = {c["question_id"]: c for c in cases}
    if len(cases) != 32 or len(cases_by_id) != 32:
        raise ValueError("incomplete paired flat-format study")
    if not callable(diagnose) or set(targets) != set(cases_by_id):
        raise ValueError("unregistered scoring targets for format diagnostic")
    raw = {}
    for row in answers:
        qid = row["question_id"]
        if (
            qid not in cases_by_id
            or qid in raw
            or row["phase"] != cases_by_id[qid]["phase"]
            or row["status"] not in ("succeeded", "failed")
        ):
            raise ValueError("duplicated or detached flat Reader execution")
        raw[qid] = row
    if set(raw) != set(cases_by_id):
        raise ValueError("missing zero/failed flat-format Reader records")
    old = {
        x["question_id"]: x
        for x in original_scored
        if x["stage"] == 48 and x["arm"] == "frozen_rerank"
    }
    if len(old) != 32 or set(old) != set(cases_by_id):
        raise ValueError("original frozen diagnostic answer census drift")
    groups = defaultdict(list)
    for case in cases:
        qid = case["question_id"]
        a = raw[qid]
        previous = old[qid]
        if previous["status"] != "succeeded":
            raise ValueError("pinned original Reader success changed")
        valid = a["status"] == "succeeded"
        old_f1 = previous.get("diagnostic_answer_f1")
        new_f1 = diagnose(a["answer"], targets[qid]) if valid else None
        if any(
            v is not None
            and (type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1)
            for v in (old_f1, new_f1)
        ):
            raise ValueError("invalid Reader-format diagnostic token F1")
        delta = new_f1 - old_f1 if old_f1 is not None and new_f1 is not None else None
        body = a.get("answer", "") if valid else ""
        original_answer = previous.get("answer")
        if previous["status"] != "succeeded" or not isinstance(original_answer, str):
            raise ValueError("archived original Reader answer missing")

        def serialized_question_prefix(text):
            normalized = text.lstrip().lower()
            return normalized.startswith(
                (
                    '{"question"',
                    "{'question'",
                    '"question"',
                    "'question'",
                    "question:",
                )
            )

        groups[case["phase"]].append(
            dict(
                question_id=qid,
                phase=case["phase"],
                original_f1=old_f1,
                flat_f1=new_f1,
                matched_diagnostic_f1_delta=delta,
                flat_generation_succeeded=valid,
                original_serialized_question_prefix=(
                    serialized_question_prefix(original_answer)
                ),
                flat_serialized_question_prefix=(
                    serialized_question_prefix(body) if valid else None
                ),
                original_structural_citation_markers=len(
                    CITATION.findall(original_answer)
                ),
                flat_structural_citation_markers=(
                    len(CITATION.findall(body)) if valid else None
                ),
                independent_semantic_citation_precision=None,
            )
        )
    out = {}
    for phase in PHASES:
        v = groups[phase]
        if len(v) != 8:
            raise ValueError("original 8-question Reader phase budget changed")
        known = [
            x["matched_diagnostic_f1_delta"]
            for x in v
            if x["matched_diagnostic_f1_delta"] is not None
        ]
        n, missing = len(v), len(v) - len(known)
        delta_total = math.fsum(known)
        out[phase] = dict(
            planned=n,
            flat_generation_succeeded=sum(x["flat_generation_succeeded"] for x in v),
            paired_f1_scored=len(known),
            paired_f1_missing=missing,
            paired_diagnostic_f1_delta_mean=(
                delta_total / len(known) if known else None
            ),
            all_planned_f1_delta_bounds=[
                (delta_total - missing) / n,
                (delta_total + missing) / n,
            ],
            original_serialized_question_prefixes=sum(
                x["original_serialized_question_prefix"] for x in v
            ),
            flat_serialized_question_prefixes=sum(
                x["flat_serialized_question_prefix"] is True for x in v
            ),
            original_structural_citation_markers=sum(
                x["original_structural_citation_markers"] for x in v
            ),
            flat_structural_citation_markers=sum(
                x["flat_structural_citation_markers"] or 0 for x in v
            ),
            semantic_citation_precision=None,
            production_accepted=False,
        )
    return dict(
        schema="hepta.stem-frozen-reader-flat-vs-json-diagnostic.v1",
        original_archive_commit=ARCHIVED_SOURCE,
        planned_questions=32,
        frozen_reader_model_and_system_prompt_unchanged=True,
        only_user_payload_format_changed=True,
        model_updates=0,
        independent_human_oracle_verified=False,
        format_change_not_a_memory_learning_gain=True,
        semantic_citation_precision=None,
        phases=out,
        rows=[q for phase in PHASES for q in groups[phase]],
        production_accepted=False,
    )
