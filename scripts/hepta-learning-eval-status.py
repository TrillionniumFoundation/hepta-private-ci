#!/usr/bin/env python3
"""Generate lexical source status; execution and acceptance remain external facts."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from hepta_rust_identifiers import contains_rust_identifier
from hepta_learning_eval_projection import canonical, projection, replace_projection

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.json"
IMPLEMENTATION_MAP = ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"
DOCUMENTS = [ROOT / "docs/modules/learning.eval/TECHNICAL.md",
             ROOT / "codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md"]
EVAL_ROOT = ROOT / "codex-rs/hepta-intelligence-eval"
SRC = "codex-rs/hepta-intelligence-eval/src/"
LOW_LEVEL_V2 = "decide_with_signed_evidence_v2"
LOW_LEVEL_V3 = "decide_with_signed_longitudinal_evidence_v3"
RAW_PRODUCT_RUNNER = "ProductEvaluationRunnerV1"
CALLERS = [
    {"kind": "consumer_bound_admission", "sourcePath": "codex-rs/hepta-agentd/src/intelligence_evaluation.rs", "nativeSymbol": "AgentdEvaluationSessionV1::evaluate", "authority": "deny_all"},
    {"kind": "consumer_bound_admission", "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs", "nativeSymbol": "propose_authenticated_parameter_plasticity_v1", "authority": "deny_all"},
    {"kind": "sealed_product_qualification_consumer", "sourcePath": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs", "nativeSymbol": "run_evaluated_shadow_v1", "authority": "deny_all"},
]
RECOVERY_OPERATIONS = [
    ("AnchoredProductEvaluationAttemptJournalV1", "attempt_journal_anchor.rs", SRC + "attempt_journal_tests.rs"),
    ("reconcile_product_attempt_holdout_v1", "attempt_recovery.rs", SRC + "recorded_runner_process_tests.rs"),
    ("reconcile_product_attempt_publication_v1", "attempt_recovery.rs", SRC + "recorded_publication_tests.rs"),
    ("RecordedPublicationSinkV1", "recorded_publication.rs", SRC + "recorded_publication_tests.rs"),
    ("DurableProductEvaluationAttemptJournalV1", "attempt_durability.rs", "scripts/hepta-learning-eval-api-surface.sh"),
    ("RecordedProductEvaluationRunnerV1::reconcile_pending_page", "attempt_recovery.rs", SRC + "attempt_recovery_tests.rs"),
    ("RecordedProductEvaluationRunnerV1::resume_decided_qualification", "attempt_publication_resume.rs", "scripts/hepta-learning-eval-api-surface.sh"),
    ("RecordedProductEvaluationRunnerV1::resume_decided_outcome_qualification", "attempt_publication_resume.rs", "scripts/hepta-learning-eval-api-surface.sh"),
    ("RecordedProductEvaluationRunnerV1::resume_decided_publication", "attempt_publication_resume.rs", SRC + "recorded_runner_process_tests.rs"),
    ("freeze_product_outcome_plan_v1", "outcome_channels.rs", SRC + "outcome_tests.rs"),
    ("product_outcome_inputs_digest_v1", "outcome_payload.rs", SRC + "outcome_tests.rs"),
    ("RecordedProductEvaluationRunnerV1::evaluate_outcome_comparison", "outcome_runner.rs", SRC + "outcome_tests.rs"),
    ("RecordedProductEvaluationRunnerV1::qualify_outcomes_and_persist", "outcome_runner.rs", SRC + "outcome_tests.rs"),
]
REPOSITORY_GAPS = [
    "Execute formatting, compilation, tests, strict lint and coverage on the final exact source and ordered-parent merge tree.",
    "Persist and recover complete sealed evidence objects, not only their digests, across computation and publication crashes.",
    "Complete signed outcome/recovery end-to-end tests and a downstream consumer of the sealed multi-outcome qualification receipt.",
    "Compose a real selected-host controller with authenticated independent anchor authority, provider, publication store and persistent recovery cursors.",
    "Qualify near-capacity startup, backlog, checkpoint/rotation and sustained recovery on the selected storage topology.",
]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def direct_external_callers(symbol: str) -> list[str]:
    return [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "codex-rs").rglob("*.rs"))
            if EVAL_ROOT not in path.parents and contains_rust_identifier(path.read_text(encoding="utf-8"), symbol)]


def external_production_callers(symbol: str) -> list[str]:
    # Lexical inventory, not a call graph. Keep inline cfg/test and macro bodies
    # conservatively; external compiler fixtures independently check default ABI.
    return [path for path in direct_external_callers(symbol)
            if "/tests/" not in path and not path.endswith(("_tests.rs", "_test_support.rs"))]


def require_token(path: str, token: str) -> None:
    if token not in read(path):
        raise SystemExit(f"{path}: missing required source token {token!r}")


def verify_implementation_map(callers: list[dict]) -> None:
    value = json.loads(IMPLEMENTATION_MAP.read_text(encoding="utf-8"))
    if value.get("module") != "learning.eval":
        raise SystemExit("implementation map module identity mismatch")
    required = {
        "RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison",
        "RecordedProductEvaluationRunnerV1::qualify_and_persist",
        "admit_signed_eligibility_v2", "ReconciledProductQualificationSinkV1::persist",
        "LockedFileProductEvaluationAttemptJournalV1", "LockedFileFinalHoldoutCasStoreV1::compact_into",
        "decide_with_signed_evidence_v2", "decide_with_signed_longitudinal_evidence_v3",
    } | {row[0] for row in RECOVERY_OPERATIONS}
    rows = value.get("operations", [])
    operations = {row["nativeSymbol"]: row for row in rows}
    if len(operations) != len(rows):
        raise SystemExit("duplicate native operation identity")
    if required - operations.keys():
        raise SystemExit(f"missing mapped operations: {sorted(required - operations.keys())}")
    for symbol, source, test in RECOVERY_OPERATIONS:
        entry = operations[symbol]
        if entry.get("sourcePath") != SRC + source:
            raise SystemExit(f"incorrect source path for {symbol}")
        require_token(SRC + source, symbol.rsplit("::", 1)[-1])
        if test not in entry.get("tests", []) or not (ROOT / test).is_file():
            raise SystemExit(f"missing recovery/outcome test mapping for {symbol}")
    def identities(items: list[dict]) -> set[tuple]:
        return {(row.get("sourcePath"), row.get("nativeSymbol"), row.get("authority")) for row in items}
    if identities(value.get("productCallers", [])) != identities(callers):
        raise SystemExit("implementation-map caller inventory differs from source inventory")
    if value.get("repositoryControlledGaps") != REPOSITORY_GAPS:
        raise SystemExit("implementation-map open obligations differ from canonical status")
    boundary = value.get("claimBoundary", {})
    for field in ("consumerBoundAdmissionComposed", "durableAttemptJournalImplemented", "publicationReconciliationImplemented", "verifiedCompactionImplemented"):
        if boundary.get(field) is not True:
            raise SystemExit(f"source claim boundary drift: {field}")
    for field in ("productionImplementation", "targetHostQualified", "independentAcceptance", "activation", "release"):
        if boundary.get(field) is not False:
            raise SystemExit(f"external claim must not be self-issued: {field}")


def expected_source_facts() -> dict:
    # Materialized/lexical facts only. No invocation or execution is inferred.
    return {
        "lowLevelDecisionPrimitivesCratePrivate": True,
        "externalLowLevelDecisionCallers": [],
        "externalRawProductRunnerCallers": [],
        "externalRawRunnerReferencesAbsentInLexicalInventory": True,
        "consumerBoundAdmission": True,
        "idempotentPublicationReconciliation": True,
        "durableEvaluationAttemptJournal": True,
        "verifiedHoldoutCompaction": True,
        "implementationMapVerified": True,
        "callers": CALLERS,
        "recoverySource": {
            "defaultRawRunnerFeatureGated": True,
            "defaultRecordedRunnerRequiresAnchoredJournalCapability": True,
            "preConsumptionIntent": True,
            "independentAttemptAnchorProtocol": True,
            "writeAheadPublicationPhases": True,
            "boundedPendingDiscovery": True,
            "cursorAdvancesPastUnresolvedAttempts": True,
            "fullHistoryValidation": True,
            "externalOwnerReadOnlyReconciliation": True,
            "decidedOnlyResumeReverifiesSignatures": True,
            "unverifiedResumeHelperCratePrivate": True,
            "incrementalAppendAndStreamingReplay": True,
            "processKillFixtureCutCount": 7,
            "executionStatus": "not_established_by_source_scan",
        },
        "outcomeSource": {
            "typedFrozenChannelContracts": True,
            "completePayloadDigestBinding": True,
            "separateNativeChannelEstimates": True,
            "singleConsumptionRecordedComposition": True,
            "maximumChannels": 32,
            "maximumBatchRows": 100000,
            "downstreamConsumer": "requires_composition_and_execution_evidence",
            "measurementAuthentication": "requires_selected_host_evidence",
            "executionStatus": "not_established_by_source_scan",
        },
    }


def source_facts() -> dict:
    lib = read(SRC + "lib.rs")
    required = [
        ("lib.rs", "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;"),
        ("lib.rs", "pub(crate) use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;"),
        ("lib.rs", "pub use signed_admission::admit_signed_eligibility_v2;"),
        ("lib.rs", "pub use reconciled_sink::ReconciledProductQualificationSinkV1;"),
        ("lib.rs", "pub use attempt_journal::LockedFileProductEvaluationAttemptJournalV1;"),
        ("lib.rs", "pub use recorded_runner::RecordedProductEvaluationRunnerV1;"),
        ("lib.rs", '#[cfg(feature = "trusted-inprocess-eval")]\npub use product_runner::ProductEvaluationRunnerV1;'),
        ("signed_admission.rs", "SignedEligibilityAdmissionReceiptV1"),
        ("reconciled_sink.rs", "accepted_unknown_is_reconciled_without_duplicate_publish"),
        ("reconciled_sink.rs", "concurrent_identical_commit_is_reconciled_as_idempotent_success"),
        ("attempt_journal_tests.rs", "truncated_frame_and_second_writer_are_rejected"),
        ("attempt_journal_tests.rs", "complete_old_prefix_is_rejected_by_independent_anchor"),
        ("recorded_runner_tests.rs", "journal_failure_preserves_consumed_holdout_and_blocks_release"),
        ("recorded_runner_tests.rs", "durable_intent_failure_precedes_all_provider_and_holdout_calls"),
        ("recorded_publication_tests.rs", "absent_record_after_unknown_never_triggers_a_second_write"),
        ("attempt_journal_file.rs", "recover_with_anchor"),
        ("attempt_journal_file.rs", "read_exact"),
        ("attempt_journal.rs", "IntentPersisted"),
        ("attempt_journal.rs", "pending_page"),
        ("recorded_runner.rs", "J: DurableProductEvaluationAttemptJournalV1"),
        ("recorded_runner.rs", '#[path = "outcome_runner.rs"]'),
        ("recorded_publication.rs", '#[path = "attempt_publication_resume.rs"]'),
        ("attempt_recovery.rs", "validated_history"),
        ("attempt_recovery_tests.rs", "pending_cursor_advances_past_unresolved_attempts"),
        ("attempt_recovery_tests.rs", "individually_valid_frames_cannot_be_spliced_across_attempts"),
        ("attempt_publication_resume.rs", "pub(crate) fn resume_decided_publication"),
        ("attempt_publication_resume.rs", "verify_decision"),
        ("outcome_channels.rs", "const MAX_CHANNELS: usize = 32;"),
        ("outcome_channels.rs", "const MAX_BATCH_ROWS: usize = 100_000;"),
        ("outcome_tests.rs", "measured_channels_with_same_estimator_have_distinct_intervals_and_one_consumption"),
        ("outcome_tests.rs", "swapping_payloads_without_changing_frozen_contracts_fails_after_consumption"),
        ("fenced_holdout_file.rs", "compact_into"),
    ]
    for path, token in required:
        require_token(SRC + path, token)
    for stage in ("consume_before_attempt", "consumed_before_release", "computed_before_seal", "sealed_before_publication", "decided_before_pending", "pending_before_write", "publication_ack_lost"):
        require_token(SRC + "recorded_runner_process_tests.rs", stage)
    require_token("scripts/hepta-learning-eval-api-surface.sh", "E0624")
    require_token("codex-rs/hepta-intelligence-eval/tests/holdout_compaction.rs", "compaction_replays_nonempty_holdout_journal_without_semantic_drift")
    for symbol, module in ((LOW_LEVEL_V2, "signed_evaluation"), (LOW_LEVEL_V3, "longitudinal_time")):
        if f"pub use {module}::{symbol};" in lib or direct_external_callers(symbol):
            raise SystemExit(f"external low-level ingress remains: {symbol}")
    raw_callers = external_production_callers(RAW_PRODUCT_RUNNER)
    if raw_callers:
        raise SystemExit(f"external raw product runner references: {raw_callers}")
    for caller in CALLERS:
        require_token(caller["sourcePath"], "ProductQualificationReceiptV1" if caller["kind"] == "sealed_product_qualification_consumer" else "admit_signed_eligibility_v2")
    verify_implementation_map(CALLERS)
    return expected_source_facts()


def render() -> dict:
    return {
        "schema": "hepta.learning-eval.current-status.v1",
        "module": "learning.eval",
        "statusSemantics": "Generated lexical source inventory only; compilation, product invocation, exact-head execution, selected-host qualification and independent acceptance are separate facts.",
        "sourceFacts": source_facts(),
        "repositoryControlledGaps": REPOSITORY_GAPS,
        "qualification": {
            "exactHead": "requires_passing_commit_addressed_ci_artifact",
            "orderedParentSyntheticMerge": "requires_passing_commit_addressed_ci_artifact",
            "coverageThresholdPct": 85,
            "targetHost": "requires_authenticated_external_host_evidence",
            "crossHostFilesystem": "requires_external_linearizability_and_fsync_qualification",
        },
        "externalEvidenceGates": [
            "real future-calendar observations and independent outcome provenance",
            "retention, change-point, statistical power, subgroup and privacy evidence",
            "unlearning and backup non-resurrection evidence",
            "independent semantic and operator acceptance",
            "selection, canary, promotion and release authority",
        ],
        "claims": {"productionImplementation": False, "targetHostQualified": False,
                   "independentAcceptance": False, "activation": False, "release": False},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write", "verify", "print"))
    args = parser.parse_args()
    if args.command == "verify":
        for pattern in ("test_hepta_rust_identifiers.py", "test_hepta_learning_eval_projection.py"):
            subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "scripts"),
                            "-p", pattern], check=True)
    value = render()
    rendered = canonical(value)
    if args.command == "print":
        print(rendered, end="")
        return
    block = projection(value)
    replacements = {path: replace_projection(path.read_text(encoding="utf-8"), block) for path in DOCUMENTS}
    if args.command == "write":
        # Explicit authoring command only. Qualification always invokes verify.
        STATUS.write_text(rendered, encoding="utf-8")
        for path, content in replacements.items():
            path.write_text(content, encoding="utf-8")
        print(json.dumps({"written": [str(path.relative_to(ROOT)) for path in [STATUS, *DOCUMENTS]]}))
        return
    stale = []
    if not STATUS.is_file() or STATUS.read_text(encoding="utf-8") != rendered:
        stale.append(str(STATUS.relative_to(ROOT)))
    stale.extend(str(path.relative_to(ROOT)) for path, content in replacements.items()
                 if path.read_text(encoding="utf-8") != content)
    if stale:
        raise SystemExit(f"learning.eval source projections are stale: {stale}; author with hepta-learning-eval-status.py write")
    print(json.dumps({"status": "ok", "evidenceClass": "lexical_source_inventory", "documentsChecked": len(DOCUMENTS)}))


if __name__ == "__main__":
    main()
