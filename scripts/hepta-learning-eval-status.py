#!/usr/bin/env python3
"""Generate and verify the source-truth status for learning.eval.

This script proves repository source facts only. It deliberately does not turn a
passing source scan into exact-head qualification, target-host qualification,
future-calendar evidence, independent acceptance, promotion, or release.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs/modules/learning.eval/CURRENT_STATUS.json"
IMPLEMENTATION_MAP = ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"
EVAL_ROOT = ROOT / "codex-rs/hepta-intelligence-eval"

LOW_LEVEL_V2 = "decide_with_signed_evidence_v2"
LOW_LEVEL_V3 = "decide_with_signed_longitudinal_evidence_v3"
RAW_PRODUCT_RUNNER = "ProductEvaluationRunnerV1"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def direct_external_callers(symbol: str) -> list[str]:
    callers: list[str] = []
    rust_root = ROOT / "codex-rs"
    for path in sorted(rust_root.rglob("*.rs")):
        if EVAL_ROOT in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if symbol in text:
            callers.append(path.relative_to(ROOT).as_posix())
    return callers


def external_production_callers(symbol: str) -> list[str]:
    """Find non-test product code that directly references a compatibility API."""
    callers: list[str] = []
    rust_root = ROOT / "codex-rs"
    for path in sorted(rust_root.rglob("*.rs")):
        if EVAL_ROOT in path.parents:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if (
            "/tests/" in relative
            or path.name.endswith("_tests.rs")
            or path.name.endswith("_test_support.rs")
        ):
            continue
        text = path.read_text(encoding="utf-8")
        if symbol in text:
            callers.append(relative)
    return callers


def require_token(path: str, token: str) -> None:
    if token not in read(path):
        raise SystemExit(f"{path}: missing required token {token!r}")


def verify_implementation_map(callers: list[dict]) -> None:
    if not IMPLEMENTATION_MAP.is_file():
        raise SystemExit(
            f"missing implementation map: {IMPLEMENTATION_MAP.relative_to(ROOT)}"
        )
    value = json.loads(IMPLEMENTATION_MAP.read_text(encoding="utf-8"))
    if value.get("module") != "learning.eval":
        raise SystemExit("learning.eval: implementation map module identity mismatch")

    operations = {
        item.get("nativeSymbol")
        for item in value.get("operations", [])
        if isinstance(item, dict)
    }
    required_operations = {
        "RecordedProductEvaluationRunnerV1::evaluate_temporal_comparison",
        "RecordedProductEvaluationRunnerV1::qualify_and_persist",
        "admit_signed_eligibility_v2",
        "ReconciledProductQualificationSinkV1::persist",
        "LockedFileProductEvaluationAttemptJournalV1",
        "LockedFileFinalHoldoutCasStoreV1::compact_into",
        "decide_with_signed_evidence_v2",
        "decide_with_signed_longitudinal_evidence_v3",
    }
    missing = sorted(required_operations - operations)
    if missing:
        raise SystemExit(
            "learning.eval: implementation map is missing operations: "
            + ", ".join(missing)
        )

    mapped_callers = {
        (
            item.get("sourcePath"),
            item.get("nativeSymbol"),
            item.get("authority"),
        )
        for item in value.get("productCallers", [])
        if isinstance(item, dict)
    }
    expected_callers = {
        (item["sourcePath"], item["nativeSymbol"], item["authority"])
        for item in callers
    }
    if mapped_callers != expected_callers:
        raise SystemExit(
            "learning.eval: implementation-map caller inventory differs from generated truth"
        )

    boundary = value.get("claimBoundary", {})
    required_boundary = {
        "consumerBoundAdmissionComposed": True,
        "durableAttemptJournalImplemented": True,
        "publicationReconciliationImplemented": True,
        "verifiedCompactionImplemented": True,
        "productionImplementation": False,
        "targetHostQualified": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
    for field, expected in required_boundary.items():
        if boundary.get(field) is not expected:
            raise SystemExit(
                f"learning.eval: implementation-map claim boundary {field!r} drifted"
            )


def source_facts() -> dict:
    lib_path = "codex-rs/hepta-intelligence-eval/src/lib.rs"
    lib = read(lib_path)
    required = [
        (lib_path, "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;"),
        (lib_path, "pub(crate) use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;"),
        (lib_path, "pub use signed_admission::admit_signed_eligibility_v2;"),
        (lib_path, "pub use reconciled_sink::ReconciledProductQualificationSinkV1;"),
        (lib_path, "pub use attempt_journal::LockedFileProductEvaluationAttemptJournalV1;"),
        (lib_path, "pub use recorded_runner::RecordedProductEvaluationRunnerV1;"),
        (
            "codex-rs/hepta-intelligence-eval/src/signed_admission.rs",
            "SignedEligibilityAdmissionReceiptV1",
        ),
        (
            "codex-rs/hepta-intelligence-eval/src/reconciled_sink.rs",
            "accepted_unknown_is_reconciled_without_duplicate_publish",
        ),
        (
            "codex-rs/hepta-intelligence-eval/src/reconciled_sink.rs",
            "concurrent_identical_commit_is_reconciled_as_idempotent_success",
        ),
        (
            "codex-rs/hepta-intelligence-eval/src/attempt_journal.rs",
            "truncated_frame_and_second_writer_are_rejected",
        ),
        (
            "codex-rs/hepta-intelligence-eval/src/recorded_runner.rs",
            "journal_failure_preserves_consumed_holdout_and_blocks_release",
        ),
        (
            "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
            "compact_into",
        ),
        (
            "codex-rs/hepta-intelligence-eval/tests/holdout_compaction.rs",
            "compaction_replays_nonempty_holdout_journal_without_semantic_drift",
        ),
    ]
    for path, token in required:
        require_token(path, token)

    if "pub use signed_evaluation::decide_with_signed_evidence_v2;" in lib:
        raise SystemExit("learning.eval: low-level V2 verifier is publicly exported")
    if "pub use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;" in lib:
        raise SystemExit("learning.eval: low-level V3 verifier is publicly exported")

    external_v2 = direct_external_callers(LOW_LEVEL_V2)
    external_v3 = direct_external_callers(LOW_LEVEL_V3)
    if external_v2 or external_v3:
        raise SystemExit(
            "learning.eval: external low-level decision callers remain: "
            + ", ".join(sorted(set(external_v2 + external_v3)))
        )

    external_raw_runner = external_production_callers(RAW_PRODUCT_RUNNER)
    if external_raw_runner:
        raise SystemExit(
            "learning.eval: product code bypasses the recorded runner: "
            + ", ".join(external_raw_runner)
        )

    caller_specs = [
        {
            "kind": "consumer_bound_admission",
            "sourcePath": "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
            "nativeSymbol": "AgentdEvaluationSessionV1::evaluate",
            "requiredToken": "admit_signed_eligibility_v2",
            "authority": "deny_all",
        },
        {
            "kind": "consumer_bound_admission",
            "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
            "nativeSymbol": "propose_authenticated_parameter_plasticity_v1",
            "requiredToken": "admit_signed_eligibility_v2",
            "authority": "deny_all",
        },
        {
            "kind": "sealed_product_qualification_consumer",
            "sourcePath": "codex-rs/hepta-intelligence/src/evaluated_shadow.rs",
            "nativeSymbol": "run_evaluated_shadow_v1",
            "requiredToken": "ProductQualificationReceiptV1",
            "authority": "deny_all",
        },
    ]
    callers: list[dict] = []
    for spec in caller_specs:
        require_token(spec["sourcePath"], spec.pop("requiredToken"))
        callers.append(spec)

    verify_implementation_map(callers)

    return {
        "lowLevelDecisionPrimitivesCratePrivate": True,
        "externalLowLevelDecisionCallers": [],
        "externalRawProductRunnerCallers": [],
        "productionRawRunnerBypassAbsent": True,
        "consumerBoundAdmission": True,
        "idempotentPublicationReconciliation": True,
        "durableEvaluationAttemptJournal": True,
        "verifiedHoldoutCompaction": True,
        "implementationMapVerified": True,
        "callers": callers,
    }


def render() -> dict:
    return {
        "schema": "hepta.learning-eval.current-status.v1",
        "module": "learning.eval",
        "statusSemantics": (
            "Generated source truth only; CI and external evidence gates are not "
            "self-issued by this document."
        ),
        "sourceFacts": source_facts(),
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
        "claims": {
            "productionImplementation": False,
            "targetHostQualified": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }


def canonical(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write", "verify", "print"))
    args = parser.parse_args()
    rendered = canonical(render())
    if args.command == "print":
        print(rendered, end="")
        return
    if args.command == "write":
        STATUS.write_text(rendered, encoding="utf-8")
        print(STATUS.relative_to(ROOT))
        return
    if not STATUS.is_file():
        raise SystemExit(f"missing generated status: {STATUS.relative_to(ROOT)}")
    current = STATUS.read_text(encoding="utf-8")
    if current != rendered:
        raise SystemExit(
            "learning.eval generated status is stale; run "
            "python3 scripts/hepta-learning-eval-status.py write"
        )
    print(json.dumps({"status": "ok", "path": str(STATUS.relative_to(ROOT))}))


if __name__ == "__main__":
    main()
