"""Post-seal verified-output BOUNDARY, not a learned Reader improvement.

Read a completed exact-identity Reader experiment without invoking any model.
An independently verified syntactic relation path may certify an unambiguous
Reader token, or the boundary abstains. Bracketed citations are minted by the
boundary and NEVER credited to the frozen Reader. Only the closed synthetic
relation grammar is supported; this is NOT a general semantic verifier.
"""

from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path
import re

from system2_multihop_completed_audit import (
    ARCHIVE_SHA,
    GENERATING_COMMIT,
    READER_IDENTITY,
    read_completed,
)
from system2_multihop_evidence import choose, join_path, parse_relation
from system2_multihop_prompt_trial import (
    ALL_PROMPT_VARIANTS,
    PROMPT_VARIANTS,
    SOURCE_ARMS,
    GENERATION_LIMIT,
    TOKEN_LIMIT,
    summarize,
)
from system2_multihop_trial import ABSTAIN, TOKEN_RE, evidence
from system2_native_receipt import strict_json, verified_archive
from native import digest as native_digest

HOSTED_PROMPT_SHA = "ff8caeea43ad029167d52107947b483a44e77e60aa92927211626ef105e935b7"
HOSTED_PROMPT_COMMIT = "98828b2f8d616856a50ca7a1abf44292a1f060e1"
HOSTED_PROMPT_TREE = "e58255ffa6e421b7dd19cda4225f188420f6591a"
HOSTED_RAW_SEAL = "2782f91d086c81bbd8434ff64b6533dbb57666acced0217af60b1899b146aa4e"
HEX = re.compile("[0-9a-f]{64}\\Z")


def hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def proof_boundary(query, selected, raw_model_answer):
    """No target/gold input: one exact model token plus a literal source path.

    Caller is responsible for original-byte provenance binding. An empty or
    incomplete relationship returns a strict system refusal, even when the
    model guessed the true token. This separately audited system renderer must
    never be scored as an unmodified neural answer or as generic reasoning.
    """
    if not isinstance(raw_model_answer, str) or not raw_model_answer.strip():
        raise ValueError("missing real model output")
    path = join_path(query, selected)
    token_hits = TOKEN_RE.findall(raw_model_answer)
    result = dict(
        model_raw_answer_unchanged=True,
        neural_generated_bracketed_citations=bool(
            re.search(r"\[E\d+\]", raw_model_answer)
        ),
        model_token_occurrences=len(token_hits),
        system_added_citations=False,
        boundary_kind="closed_synthetic_grammar_only",
        safe=False,
        independent_language_semantics_established=False,
    )
    if not path or len(token_hits) != 1:
        return result | dict(
            action="system_abstain",
            answer=ABSTAIN,
            path_complete=bool(path),
            rejection_reason=(
                "no_verifiable_relation_chain" if not path else "ambiguous_model_token"
            ),
            proof_source_ids=[],
            accepted_model_token=None,
        )
    last = parse_relation(path[-1])
    if last is None or last[2] != "token":
        raise ValueError("invalid supposed terminal edge")
    expected = last[3]
    if token_hits[0].upper() != expected:
        return result | dict(
            action="system_abstain",
            answer=ABSTAIN,
            path_complete=True,
            rejection_reason="model_token_not_entailed",
            proof_source_ids=[],
            accepted_model_token=None,
        )
    by_id = {d.identity: i for i, d in enumerate(selected, 1)}
    if len(by_id) != len(selected) or not all(p.identity in by_id for p in path):
        raise ValueError("detached proof or duplicate source")
    labels = [f"[E{by_id[p.identity]}]" for p in path]
    return result | dict(
        action="certified_system_answer",
        answer=expected + " " + " ".join(labels),
        safe=True,
        path_complete=True,
        rejection_reason=None,
        system_added_citations=True,
        accepted_model_token=expected,
        proof_source_ids=[d.identity for d in path],
    )


def authenticated_rows(archive, original_archive):
    """Reverify both outer ZIP pins, every internal member and prediction seal."""
    historic = read_completed(Path(original_archive), expected_sha=ARCHIVE_SHA)
    files = verified_archive(Path(archive), HOSTED_PROMPT_SHA)
    if (
        files["tested-commit.txt"].decode().strip() != HOSTED_PROMPT_COMMIT
        or files["tested-tree.txt"].decode().strip() != HOSTED_PROMPT_TREE
    ):
        raise ValueError("prompt experiment generating source changed")
    plan = strict_json(files["trial/plan.json"])
    cases = historic["cases"]
    if (
        plan.get("source_commit") != HOSTED_PROMPT_COMMIT
        or plan.get("original_source_commit") != GENERATING_COMMIT
        or plan.get("archived_original_sha256") != ARCHIVE_SHA
        or plan.get("archived_raw_answer_sha256") != historic["seal"]["sha256"]
        or plan.get("required_reader_identity") != READER_IDENTITY
        or plan.get("new_reader_calls") != 180
        or plan.get("original_calls_reused") != 60
        or plan.get("question_ids") != [c.question.identity for c in cases]
        or plan.get("evidence_arms") != list(SOURCE_ARMS)
        or plan.get("prompt_variants") != list(ALL_PROMPT_VARIANTS)
        or plan.get("production_accepted") is not False
    ):
        raise ValueError("prompt registration or Reader source identity drift")
    raw = files["trial/new-raw-answers.jsonl"]
    seal = strict_json(files["trial/new-answer-seal.json"])
    if hash_bytes(raw) != HOSTED_RAW_SEAL or seal != dict(
        sha256=HOSTED_RAW_SEAL, rows=180, scoring_started=False
    ):
        raise ValueError("raw frozen model answer seal changed")
    rows = [strict_json(line) for line in raw.splitlines()]
    expected = {
        (c.question.identity, arm, v)
        for c in cases
        for arm in SOURCE_ARMS
        for v in PROMPT_VARIANTS
    }
    observed = [(r["qid"], r["arm"], r["prompt_variant"]) for r in rows]
    if len(rows) != 180 or len(set(observed)) != 180 or set(observed) != expected:
        raise ValueError("failed, duplicate, missing, or extra Reader invocation")
    lookup = {c.question.identity: c for c in cases}
    outputs = {}
    profiles = {}
    new_scored = []
    for row in rows:
        qid, arm, v = row["qid"], row["arm"], row["prompt_variant"]
        if (
            row["status"] != "succeeded"
            or not isinstance(row["answer"], str)
            or not row["answer"].strip()
        ):
            raise ValueError("missing or failed frozen Reader response")
        c = lookup[qid]
        selected = choose(arm, c.question, c.documents)
        if row["selected"] != [d.identity for d in selected]:
            raise ValueError("source selection changed")
        bundle, _, _ = evidence(c, selected, arm)
        rec = row["reader"]
        if (
            row["evidence_bundle_digest"] != bundle.seal()
            or rec["bundle_digest"] != bundle.seal()
            or rec["query_digest"] != native_digest(asdict(c.question))
            or rec["reader_identity"] != READER_IDENTITY
            or rec["trainable_parameters"] != 0
            or rec["answer_postprocessed"] is not False
            or rec["production_accepted"] is not False
            or rec["token_limit"] != TOKEN_LIMIT
            or rec["omitted_evidence_bytes"] != 0
            or type(rec["input_tokens"]) is not int
            or not 0 < rec["input_tokens"] <= TOKEN_LIMIT
            or type(rec["generated_tokens"]) is not int
            or not 0 < rec["generated_tokens"] <= GENERATION_LIMIT
        ):
            raise ValueError("Reader identity/compute/source receipt mismatch")
        delivered = rec["delivered_evidence"]
        if len(delivered) != len(selected) or any(
            d["original_id"] != s.identity
            or d["label"] != f"E{i + 1}"
            or d["excerpt"] != s.content
            or d["scope"] != s.scope
            or d["root"] != s.root
            or d["observed_at"] != s.observed_at
            or d["source_digest"] != native_digest(s.content)
            or d["source_start"] != 0
            or d["source_end"] != len(s.content.encode())
            for i, (d, s) in enumerate(zip(delivered, selected, strict=True))
        ):
            raise ValueError("Reader delivered evidence detached from original bytes")
        if any(
            not isinstance(rec[k], str) or not HEX.fullmatch(rec[k])
            for k in ("input_ids_digest", "generated_ids_digest", "reader_profile")
        ):
            raise ValueError("malformed frozen model token/profile digest")
        if v in profiles and profiles[v] != rec["reader_profile"]:
            raise ValueError("one variant changed tokenizer/Reader profile")
        profiles[v] = rec["reader_profile"]
        signature = (
            rec["reader_identity"],
            rec["reader_profile"],
            rec["query_digest"],
            rec["input_ids_digest"],
        )
        generated = (row["answer"], rec["generated_ids_digest"])
        if signature in outputs and outputs[signature] != generated:
            raise ValueError("deterministic Reader prompt changed answer")
        outputs[signature] = generated
        new_scored.append(row)
    # Reproduce every archived score before running the independent boundary.
    all_rows = []
    for old in historic["rows"]:
        if old["arm"] in SOURCE_ARMS:
            all_rows.append(
                dict(
                    qid=old["qid"],
                    arm=old["arm"],
                    prompt_variant="original",
                    selected=old["selected"],
                    answer=old["answer"],
                    reader=old["reader"],
                    status="succeeded",
                )
            )
    all_rows += new_scored
    recalculated = summarize(all_rows, cases)
    original_scored = strict_json(files["trial/scored.json"])
    original_summary = strict_json(files["trial/summary.json"])
    for key in (
        "groups",
        "candidate_disposition",
        "primary_candidate",
        "primary_pregate",
    ):
        if recalculated[key] != original_summary[key]:
            raise ValueError("original prompt scores no longer replay")
    if recalculated["scored"] != original_scored:
        raise ValueError("original per-answer scores no longer replay")
    if (
        original_summary["new_raw_sha256"] != HOSTED_RAW_SEAL
        or original_summary["new_calls"] != 180
    ):
        raise ValueError("original prompt summary receipt drift")
    return dict(
        historical=historic,
        files=files,
        rows=all_rows,
        cases=cases,
        profiles=profiles,
        unique_requests=len(outputs),
        manifest_entries=len(files) - 1,
        sealed_sha256=HOSTED_RAW_SEAL,
    )


def audit(audited):
    cases = {c.question.identity: c for c in audited["cases"]}
    rows = audited["rows"]
    report = []
    per_case = []
    for v in ALL_PROMPT_VARIANTS:
        for arm in SOURCE_ARMS:
            subset = [r for r in rows if r["prompt_variant"] == v and r["arm"] == arm]
            if len(subset) != 20:
                raise ValueError("missing arm/variant")
            counts = dict(
                verified=0,
                system_abstained=0,
                reader_exact_refusal=0,
                reader_bracketed_citation=0,
                readers_correct_literal=0,
                JSON_echo=0,
                unsupported_target_copy=0,
                ceiling=0,
                system_citations_minted=0,
                total_input_tokens=0,
                total_generated_tokens=0,
            )
            for row in subset:
                case = cases[row["qid"]]
                selected = choose(arm, case.question, case.documents)
                product = proof_boundary(case.question, selected, row["answer"])
                if product["action"] == "certified_system_answer":
                    # Check only after the complete, original model text was sealed.
                    if product["accepted_model_token"] != case.answer or not set(
                        product["proof_source_ids"]
                    ) == set(case.required_ids):
                        raise ValueError("boundary returned an invalid synthetic proof")
                elif product["answer"] != ABSTAIN:
                    raise ValueError("unsafe boundary refusal text")
                counts["verified"] += product["action"] == "certified_system_answer"
                counts["system_abstained"] += product["action"] == "system_abstain"
                counts["reader_exact_refusal"] += (
                    row["answer"].strip().strip('"').casefold() == ABSTAIN.casefold()
                )
                counts["reader_bracketed_citation"] += product[
                    "neural_generated_bracketed_citations"
                ]
                counts["readers_correct_literal"] += case.answer in row["answer"]
                counts["JSON_echo"] += row["answer"].lstrip().startswith('{"question"')
                counts["unsupported_target_copy"] += bool(
                    not product["path_complete"] and case.answer in row["answer"]
                )
                counts["ceiling"] += (
                    row["reader"]["generated_tokens"] == GENERATION_LIMIT
                )
                counts["system_citations_minted"] += product["system_added_citations"]
                counts["total_input_tokens"] += row["reader"]["input_tokens"]
                counts["total_generated_tokens"] += row["reader"]["generated_tokens"]
                per_case.append(
                    dict(
                        qid=row["qid"],
                        prompt_variant=v,
                        arm=arm,
                        model_answer_sha256=hash_bytes(row["answer"].encode("utf8")),
                        system_decision=product["action"],
                        source_ids=product["proof_source_ids"],
                        system_answer=product["answer"],
                        rejection_reason=product.get("rejection_reason"),
                    )
                )
            report.append(dict(prompt_variant=v, arm=arm, planned=20, **counts))
    return dict(
        schema="hepta.system2.verified-answer-boundary.v1",
        original_source_sha256=ARCHIVE_SHA,
        hosted_prompt_sha256=HOSTED_PROMPT_SHA,
        hosted_prompt_source_commit=HOSTED_PROMPT_COMMIT,
        hosted_raw_sha256=audited["sealed_sha256"],
        source_archive_files=audited["manifest_entries"],
        distinct_synthetic_questions=len(cases),
        neural_new_calls=0,
        scored_reply_rows=len(rows),
        group_results=report,
        per_question_results=per_case,
        neural_reader_accuracy_improved=False,
        reader_itself_generated_boundary_citations=False,
        external_grammar_supports_only_this_synthetic_domain=True,
        independent_human_semantics=False,
        production_accepted=False,
        decision="static_closed_world_control_not_a_learned_NDU_or_Reader_gain",
    )


def run(original_archive: Path, prompt_archive: Path, output: Path):
    if output.exists():
        raise ValueError("refuse overwrite")
    verified = authenticated_rows(prompt_archive, original_archive)
    result = audit(verified)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False
        )
        + "\n"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("prompt", type=Path)
    parser.add_argument("output", type=Path)
    a = parser.parse_args()
    result = run(a.original, a.prompt, a.output)
    print(
        json.dumps(
            dict(
                groups=result["group_results"],
                decision=result["decision"],
                neural_new_calls=0,
            ),
            allow_nan=False,
        )
    )
