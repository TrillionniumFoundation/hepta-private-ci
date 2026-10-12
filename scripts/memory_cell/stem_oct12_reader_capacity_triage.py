"""Byte-pinned, post-answer Reader evidence-sufficiency diagnosis (NOT admission).

Triangulate NO evidence, original frozen ranker evidence, and the privileged
answer-conditioned literal-span oracle on the same 32 registered questions.
Never promote the oracle to independent source verification or train any model.
"""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path

from stem_audit_archive import PinnedArchive, require
from stem_oct12_strict_nonpromotion import (
    SOURCE, TREE, ZIP_SHA256, ORIGINAL_RUN, ARTIFACT_ID,
)

PHASES = ("select", "retention", "test", "transfer")
STAGES = (16, 32, 48)
ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")
KINDS = ("native-source-literal-span",
         "no-admitted-literal-reference-span", "annotated-unanswerable")


def _key(row):
    return (row["phase"], row["question_id"])


def _rows_by_key(rows, expected, name):
    observed = {}
    for row in rows:
        key = _key(row)
        require(key in expected and key not in observed,
                "unregistered/duplicate " + name)
        observed[key] = row
    require(set(observed) == expected, "incomplete " + name + " census")
    return observed


def _score(value):
    require(value is None or
            (type(value) in (float, int) and math.isfinite(value)
             and 0.0 <= value <= 1.0),
            "nonfinite or unbounded original token-F1 receipt")
    return value


def _mean(rows, field):
    values = [row[field] for row in rows if row[field] is not None]
    return math.fsum(values) / len(values) if values else None


def triage(plan, policies, oracle, zero_raw, zero_scored, ceiling):
    """All annotations are already in frozen POST-policy archived records."""
    require(
        plan["source_commit"] == SOURCE
        and plan["production_accepted"] is False
        and plan["source_visibility_policy"] ==
            "strict-as-of-before-index-and-every-Encoder-v1"
        and tuple(plan["arms"]) == ARMS
        and tuple(plan["curriculum_attempted_examples"]) == STAGES,
        "unregistered source, Reader or chronological admission",
    )
    questions = plan["questions"]
    require(set(questions) == {"train", *PHASES}
            and len(questions["train"]) == 48
            and all(len(questions[p]) == 8 for p in PHASES),
            "registered 32-answer evaluation census missing")
    keys = {(phase, qid) for phase in PHASES for qid in questions[phase]}
    require(len(keys) == 32
            and len(set(q for ids in questions.values() for q in ids)) == 80,
            "duplicated question across training/held-out partitions")
    expected_policy = {(stage, p, q, arm) for stage in STAGES
                       for p in PHASES for q in questions[p] for arm in ARMS}
    actual = {}
    for row in policies:
        key = (row["stage"], row["phase"], row["question_id"], row["arm"])
        require(key in expected_policy and key not in actual,
                "missing/duplicate native policy prediction")
        actual[key] = row
    require(len(policies) == 576 and set(actual) == expected_policy,
            "incomplete original six-arm policy census")

    base = {
        (phase, qid): actual[(48, phase, qid, "frozen_rerank")]
        for phase, qid in keys
    }
    oracle_rows = _rows_by_key(oracle, keys, "privileged oracle")
    zero_rows = _rows_by_key(zero_raw, keys, "zero-evidence raw")
    zero_scores = _rows_by_key(zero_scored, keys, "zero-evidence scored")
    require(ceiling["final_checkpoint"] == 48
            and ceiling["independent_semantic_review_performed"] is False,
            "source ceiling must be postpolicy and non-adjudicated")
    ceiling_rows = _rows_by_key(ceiling["decisions"], keys, "source ceiling")
    detailed = []
    for phase in PHASES:
        for qid in questions[phase]:
            key = (phase, qid)
            f, o, z, zscore, cap = (
                base[key], oracle_rows[key], zero_rows[key],
                zero_scores[key], ceiling_rows[key],
            )
            kind = o["oracle_kind"]
            require(kind in KINDS
                    and o["policy_comparator"] is False
                    and o["semantic_entailment_independently_verified"] is False
                    and z["status"] == zscore["status"]
                    and z["evidence_count"] == 0
                    and z["answer_target_opened_by_generation"] is False
                    and zscore["was_zero_evidence"] is True
                    and z["family"] == f["family"] == cap["source_family"]
                    and zscore["family"] == f["family"],
                    "oracle/control label, phase or family drift")
            require(
                (kind == "annotated-unanswerable") ==
                    cap["native_source_unanswerable"]
                and (kind != "native-source-literal-span"
                     or cap["weak_native_support_resolved"] is True),
                "answerability or native literal source cannot be promoted",
            )
            f_receipt = f.get("receipt")
            z_receipt = z.get("receipt")
            if f["status"] == "succeeded" and z["status"] == "succeeded":
                require(isinstance(f_receipt, dict)
                        and isinstance(z_receipt, dict)
                        and z_receipt["delivered_evidence"] == []
                        and f_receipt["generator_identity"] ==
                            z_receipt["generator_identity"]
                        and f_receipt["generator_profile"] ==
                            z_receipt["generator_profile"]
                        and f_receipt["observable_query"] ==
                            z_receipt["observable_query"]
                        and f_receipt["observable_query"]["identity"] == qid,
                        "frozen/empty Reader source or model identity drift")
            literal = kind == "native-source-literal-span"
            if literal:
                require(o["status"] == "succeeded"
                        and len(o["receipt"]["delivered_evidence"]) == 1
                        and o["receipt"]["generator_identity"] ==
                            f_receipt["generator_identity"]
                        and o["receipt"]["generator_profile"] ==
                            f_receipt["generator_profile"]
                        and o["receipt"]["observable_query"] ==
                            f_receipt["observable_query"],
                        "privileged literal oracle is not matched to Reader")
            elif kind == "no-admitted-literal-reference-span":
                require(o["status"] == "unavailable"
                        and "receipt" not in o and "answer" not in o,
                        "unavailable oracle must not invent an answer")
            else:
                require(o["status"] == "succeeded"
                        and o["receipt"]["delivered_evidence"] == [],
                        "annotated-unanswerable oracle has evidence")
            f1 = _score(f.get("diagnostic_answer_f1"))
            no = _score(zscore.get("diagnostic_answer_f1"))
            oraf1 = _score(o.get("diagnostic_f1"))
            require(not literal or oraf1 is not None,
                    "literal-span Reader F1 not observed")
            detailed.append(dict(
                question_identity_sha256=sha256(qid.encode()).hexdigest(),
                phase=phase, oracle_kind=kind,
                original_frozen_reader_succeeded=f["status"] == "succeeded",
                empty_reader_succeeded=z["status"] == "succeeded",
                native_source_in_retrieval_pool=
                    cap["native_support_available_in_pool"],
                frozen_selected_native_source=
                    cap["frozen_selected_native_support"],
                frozen_diagnostic_f1=f1,
                no_evidence_diagnostic_f1=no,
                literal_oracle_diagnostic_f1=oraf1 if literal else None,
                literal_oracle_vs_empty_f1=(
                    oraf1 - no if literal and no is not None else None
                ),
                literal_oracle_vs_frozen_f1=(
                    oraf1 - f1 if literal and f1 is not None else None
                ),
                answer_conditioned_evidence_selection=literal,
                independent_evidence_sufficiency_certified=False,
                native_source_not_window_entailment=True,
            ))
    report = {}
    for label, subset in [
        ("all", detailed),
        *[(p, [x for x in detailed if x["phase"] == p]) for p in PHASES],
    ]:
        counts = Counter(x["oracle_kind"] for x in subset)
        literal = [x for x in subset
                   if x["oracle_kind"] == "native-source-literal-span"]
        absent = [x for x in subset
                  if x["oracle_kind"] == "no-admitted-literal-reference-span"]
        report[label] = dict(
            planned=len(subset),
            answer_conditioned_literal_span_available=len(literal),
            privileged_literal_unavailable=len(absent),
            annotated_unanswerable=counts["annotated-unanswerable"],
            literal_with_native_source_in_frozen_pool=sum(
                x["native_source_in_retrieval_pool"] is True for x in literal
            ),
            missing_literal_despite_native_source_in_pool=sum(
                x["native_source_in_retrieval_pool"] is True for x in absent
            ),
            literal_pair_scored=sum(
                x["literal_oracle_vs_empty_f1"] is not None for x in literal
            ),
            literal_vs_empty_diagnostic_f1_mean=_mean(
                literal, "literal_oracle_vs_empty_f1"
            ),
            literal_vs_frozen_diagnostic_f1_mean=_mean(
                literal, "literal_oracle_vs_frozen_f1"
            ),
            no_independent_reference_sufficiency=True,
            missing_oracle_not_reader_failure=True,
        )
    return dict(
        schema="hepta.stem-oct12-reader-capacity-triage.v1",
        original_run_id=ORIGINAL_RUN, artifact_id=ARTIFACT_ID,
        original_source_commit=SOURCE,
        original_zip_sha256=ZIP_SHA256,
        complete_original_policy_attempts=len(policies),
        original_questions=32,
        per_phase=report,
        question_receipts=detailed,
        answer_conditioned_oracle_not_blinded=True,
        independent_semantic_review_performed=False,
        all_possible_evidence_reader_capacity_proven=False,
        future_source_authority_certified=False,
        learning_arms_superior=False,
        semantic_citation_precision=None,
        scale_out_permitted=False,
        production_accepted=False,
    )


def audit_zip(path):
    archive = PinnedArchive(path, ZIP_SHA256)
    try:
        require(
            archive.read("tested-commit.txt").decode().strip() == SOURCE
            and archive.read("tested-tree.txt").decode().strip() == TREE,
            "immutable source/tree pair not pinned",
        )
        result = triage(
            archive.json("comparison/preregistered.json"),
            archive.json("comparison/scored-policy-attempts.json"),
            archive.jsonl("comparison/oracle-diagnostic.jsonl"),
            archive.jsonl("comparison/reader-no-evidence.jsonl"),
            archive.json("comparison/reader-no-evidence-report.json")["results"],
            archive.json("comparison/post-policy-native-source-ceiling.json"),
        )
        result["internal_sha256_manifest_member_count"] = archive.manifest_entries
        return result
    finally:
        archive.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zip", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = audit_zip(args.zip)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(result["per_phase"], sort_keys=True))
