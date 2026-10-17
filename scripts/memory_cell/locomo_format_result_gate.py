"""Immutable, source-only audit of the real 48-call frozen-Reader format diagnosis.

Original response text and model tensors remain outside Git. A matching
sanitized JSON receipt is not independent original-model attestation, human
semantic citation review or MemoryCell deployment authority.
"""

import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRIAL = HERE / "frozen_source" / "locomo_format_trial.py.source"
REPORT = HERE / "data" / "locomo-format-original-48-20261016.json"
SOURCE_SHA256 = "3cf5329c6d5fc500a4252e5cdbdae1f3e281dfac0cb48bc1c15b85a27bfc6ed3"
REPORT_SHA256 = "e5c70116dff96b895a342140880e801f24e4d61cfaa5b94c39b4c54fef59e12f"
LITERAL = HERE / "data" / "locomo-format-literal-audit-20261016.json"
LITERAL_SHA256 = "2947b7868efc2ca7f99897bb3196a75da6ab6b7871d06f6aca75d5647788c535"
MODEL_ZIP_SHA256 = "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
SEALED_INPUT_SHA256 = "fa7d9e676f9aca8f7c524e6f592cabb88a22c490a8c441db4bd6a8e05fbc6033"
ORIGINAL_REPLAY_RAW_SHA256 = (
    "1e36a1dcfefabf8d8912b81e215a9e7383bc4eb08a63e2dc592a0b46ce65aab3"
)
NEW_RAW_SHA256 = "1d8fc82f4843b8805709e1d60d878f0e9154099dcb0e33a773fae972e1a0b710"
EXPECTED = {
    "empty:original_json": (497, 153, 0.16666666666666666, 3, 5, 0),
    "empty:linear_evidence": (601, 124, 0.2490842490842491, 0, 0, 0),
    "empty:question_first": (761, 150, 0.1709090909090909, 0, 0, 0),
    "annotated_witness:original_json": (1809, 189, 0.1, 7, 7, 0),
    "annotated_witness:linear_evidence": (1586, 152, 0.48863636363636365, 0, 0, 5),
    "annotated_witness:question_first": (1746, 178, 1.087179487179487, 0, 0, 1),
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def source_pinned():
    for name, path, expected in (
        ("original_model_code", TRIAL, SOURCE_SHA256),
        ("sanitized_report", REPORT, REPORT_SHA256),
    ):
        require(
            path.is_file()
            and not path.is_symlink()
            and 0 < path.stat().st_size < 100_000,
            "bounded real source file required: " + name,
        )
        raw = path.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == expected,
            "pinned real source bytes mismatch: " + name,
        )
    return json.loads(REPORT.read_bytes())


def literal_pinned():
    require(
        LITERAL.is_file() and not LITERAL.is_symlink(),
        "bounded literal review required",
    )
    raw = LITERAL.read_bytes()
    require(
        0 < len(raw) < 8192 and hashlib.sha256(raw).hexdigest() == LITERAL_SHA256,
        "original sealed publisher-literal audit changed",
    )
    return json.loads(raw)


def audit_literal(record):
    require(
        isinstance(record, dict)
        and record.get("schema")
        == "hepta.memory.locomo-exposed-literal-coverage-audit.v1"
        and record.get("evaluated_old_public_conversation_roots") == 8
        and record.get("literal_target_in_one_annotated_witness") == 2
        and record.get("literal_target_in_full_root") == 2
        and record.get("literal_target_by_original_evidence_arm")
        == {"empty": 0, "bm25_top3": 1, "annotated_witness": 2, "witness_lesion": 0}
        and record.get("matched_label_source_target_only_after_seal") is True
        and record.get("missing_literal_does_not_imply_insufficient_evidence") is True
        and record.get("present_literal_does_not_certify_sufficiency") is True
        and record.get("independent_human_review") is None
        and record.get("model_training_steps") == 0
        and record.get("independent_future_families") == 0
        and record.get("complete_lifecycle_cost") is None
        and record.get("production_accepted") is False
        and record.get("decision") == "DENY_ALL",
        "postseal literal evidence misrepresented as independent sufficiency",
    )
    return {
        "publisher_annotated_witness_literal_hits": 2,
        "published_full_source_literal_hits": 2,
        "independent_sufficiency_certified": False,
        "model_calls_from_audit": 0,
        "production_accepted": False,
    }


def audit(report):
    require(
        isinstance(report, dict)
        and report.get("schema") == "hepta.memory.locomo-format-original-smol135.v1"
        and report.get("source_original_sha256") == SEALED_INPUT_SHA256
        and report.get("raw_original_journal_sha256") == NEW_RAW_SHA256
        and report.get("frozen_reader_model_zip_sha256") == MODEL_ZIP_SHA256
        and report.get("complete_real_model_requests") == 48
        and report.get("actual_successful_requests") == 48
        and report.get("source_reproduction_exact_original_requests") == 16,
        "physical original model and cross-run reproduction receipt drift",
    )
    arms = report.get("by_arm")
    require(
        isinstance(arms, dict) and set(arms) == set(EXPECTED),
        "six pre-registered paired reader conditions required",
    )
    for key, (
        input_t,
        output_t,
        f1_sum,
        json_echo,
        question_echo,
        citation,
    ) in EXPECTED.items():
        row = arms[key]
        require(isinstance(row, dict), "invalid recorded Reader outcome")
        for field in (
            "attempts",
            "successful_calls",
            "strict_correct",
            "input_tokens",
            "output_tokens",
            "json_echo",
            "question_echo",
            "citation_markers_structurally_valid",
        ):
            require(
                type(row.get(field)) is int,
                "typed original Reader count required: " + key + "/" + field,
            )
        require(
            (
                row["attempts"],
                row["successful_calls"],
                row["strict_correct"],
                row["input_tokens"],
                row["output_tokens"],
                row["json_echo"],
                row["question_echo"],
                row["citation_markers_structurally_valid"],
            )
            == (8, 8, 0, input_t, output_t, json_echo, question_echo, citation),
            "real original Reader task/prompt-echo outcome drift: " + key,
        )
        require(
            type(row.get("f1_sum")) in (int, float)
            and type(row.get("mean_diagnostic_f1")) in (int, float)
            and math.isclose(row["f1_sum"], f1_sum, abs_tol=1e-12)
            and math.isclose(row["mean_diagnostic_f1"], f1_sum / 8, abs_tol=1e-12),
            "token-F1 readout drift: " + key,
        )
        require(
            type(row.get("reader_seconds")) in (float, int)
            and math.isfinite(row["reader_seconds"])
            and row["reader_seconds"] > 0,
            "measured real reader time missing: " + key,
        )
    require(
        report.get("admission") == "DENY_ALL"
        and report.get("previous_public_evaluation_exposure") is True
        and report.get("independently_human_verified_witnesses") == 0
        and report.get("model_training_steps") == 0
        and report.get("new_source_families") == 0
        and report.get("stronger_reference_reader_executed") is False
        and report.get("external_model_operator_parity") is False
        and report.get("semantic_citation_entailment") is None
        and report.get("independent_future_windows") == 0
        and report.get("complete_lifecycle_tco") is None
        and report.get("production_accepted") is False,
        "unearned MemoryCell, citation or production qualification",
    )
    return dict(
        schema="hepta.memory.locomo-real-original-format-negative-gate.v1",
        original_model_requests=48,
        original_prompt_reproducibility=16,
        frozen_model_archive_sha256=MODEL_ZIP_SHA256,
        original_reader_response_journal_sha256=NEW_RAW_SHA256,
        previous_model_response_journal_sha256=ORIGINAL_REPLAY_RAW_SHA256,
        publisher_witness_questions_from_public_benchmark=8,
        evidence_readout_correct_among_original=0,
        evidence_readout_correct_among_linear=0,
        evidence_readout_correct_among_question_first=0,
        original_json_echo_with_annotated_witness=7,
        reformatted_json_echo_with_annotated_witness=0,
        structural_citation_markers_are_not_entailment=True,
        independent_human_semantic_judgment=None,
        new_training_or_model_forwards_from_this_auditor=0,
        improved_task_success=False,
        future_source_families_admitted=0,
        total_lifecycle_cost=None,
        production_accepted=False,
        decision="DENY_ALL",
    )


if __name__ == "__main__":
    print(
        json.dumps(
            dict(
                original_reader_format=audit(source_pinned()),
                postseal_literal_coverage=audit_literal(literal_pinned()),
            ),
            sort_keys=True,
            indent=2,
        )
    )
