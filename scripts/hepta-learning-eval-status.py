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
EVAL_ROOT = ROOT / "codex-rs/hepta-intelligence-eval"

LOW_LEVEL_V2 = "decide_with_signed_evidence_v2"
LOW_LEVEL_V3 = "decide_with_signed_longitudinal_evidence_v3"


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


def require_token(path: str, token: str) -> None:
    if token not in read(path):
        raise SystemExit(f"{path}: missing required token {token!r}")


def source_facts() -> dict:
    lib_path = "codex-rs/hepta-intelligence-eval/src/lib.rs"
    lib = read(lib_path)
    required = [
        (lib_path, "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;"),
        (lib_path, "pub(crate) use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;"),
        (lib_path, "pub use signed_admission::admit_signed_eligibility_v2;"),
        (lib_path, "pub use reconciled_sink::ReconciledProductQualificationSinkV1;"),
        (lib_path, "pub use attempt_journal::LockedFileProductEvaluationAttemptJournalV1;"),
        (
            "codex-rs/hepta-intelligence-eval/src/signed_admission.rs",
            "SignedEligibilityAdmissionReceiptV1",
        ),
        (
            "codex-rs/hepta-intelligence-eval/src/reconciled_sink.rs",
            "accepted_unknown_is_reconciled_without_duplicate_publish",
        ),
        (
            "codex-rs/hepta-intelligence-eval/src/attempt_journal.rs",
            "truncated_frame_and_second_writer_are_rejected",
        ),
        (
            "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs",
            "compact_into",
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

    return {
        "lowLevelDecisionPrimitivesCratePrivate": True,
        "externalLowLevelDecisionCallers": [],
        "consumerBoundAdmission": True,
        "idempotentPublicationReconciliation": True,
        "durableEvaluationAttemptJournal": True,
        "verifiedHoldoutCompaction": True,
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
