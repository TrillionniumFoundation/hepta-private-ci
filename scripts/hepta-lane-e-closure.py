#!/usr/bin/env python3
"""Read-only closed-world verifier for the Lane E implementation candidate.

The stable verifier core is digest-pinned below.  This entrypoint carries the
current closed-world policy so policy updates do not silently rewrite the
long-lived source/trace/workflow verification machinery.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = Path(__file__).with_name("hepta_lane_e_closure_core.py")
CORE_SHA256 = "b522fe9756461fd8c6ca80490fb51b853d7e2986212da5fbeed507fb4d31ac5e"


def _load_core() -> Any:
    raw = CORE_PATH.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != CORE_SHA256:
        raise RuntimeError(
            f"Lane E verifier core digest mismatch: expected {CORE_SHA256}, got {observed}"
        )
    spec = importlib.util.spec_from_file_location("hepta_lane_e_closure_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Lane E verifier core")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_core()
Finding = CORE.Finding
Findings = CORE.Findings
verify_symbol = CORE.verify_symbol
workflow_commands = CORE.workflow_commands

# The matrix and traceability source already contain the V2 authenticated
# operator boundary and its two native cases. Keep the verifier's closed world
# synchronized with those committed records rather than deleting newer work.
CORE.EXPECTED_CASES.update({"OP-05", "OP-06"})
CORE.EXPECTED_OPERATIONS["learning.operator"].update(
    {
        "admit_operator_regularity_with_signed_evidence_v2",
        "fit_tabular_operator_verified_v2",
        "fit_transition_model_verified_v2",
        "validate_applicability_with_signed_evidence_v2",
        "verify_tabular_operator_plan_v2",
        "verify_world_model_dataset_v2",
    }
)


def contains_raw_v1_learning_write(text: str) -> list[str]:
    """Return raw V1 event constructors that can feed a product append path.

    Pattern matching historical records during recovery is a read, not a write.
    The one qualification-only compatibility adapter is checked separately and
    is absent from default product builds.
    """

    variants: list[str] = []
    for variant in ("Decision", "Outcome", "Credit", "Revocation"):
        if re.search(
            rf"(?m)^\s*let\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*LedgerEvent::{variant}\s*\(",
            text,
        ):
            variants.append(variant)
    return variants


def verify_product_writer_exclusivity(findings: Any) -> None:
    """Reject default product writers that bypass the authenticated LedgerWriter."""

    allowed_roots = {
        "codex-rs/hepta-learning-ledger",
        "codex-rs/hepta-shadow-qualification",
    }
    qualification_compatibility = {
        "codex-rs/hepta-agentd/src/intelligence_product.rs",
        "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    }
    for path in (ROOT / "codex-rs").rglob("*.rs"):
        relative = path.relative_to(ROOT).as_posix()
        if any(
            relative == owner or relative.startswith(f"{owner}/")
            for owner in allowed_roots
        ):
            continue
        if (
            "/tests/" in relative
            or path.name.endswith("_tests.rs")
            or path.name.endswith("_test_support.rs")
        ):
            continue
        text = path.read_text(encoding="utf-8")
        variants = contains_raw_v1_learning_write(text)
        if relative in qualification_compatibility:
            findings.require(
                not variants
                or '#[cfg(feature = "qualification-legacy-learning-write")]' in text,
                "legacy_learning_writer_qualification_gate",
                f"{relative} has an ungated legacy qualification writer",
            )
            continue
        for variant in variants:
            findings.add(
                "legacy_learning_writer_product_bypass",
                f"{relative} constructs raw V1 {variant} for a product append; use LedgerWriter",
            )


# The core invokes this symbol through its module globals.
CORE.verify_product_writer_exclusivity = verify_product_writer_exclusivity


def _verify_product_evaluation_adapter(findings: Any) -> None:
    lib_path = ROOT / "codex-rs/hepta-intelligence-eval/src/lib.rs"
    adapter_path = ROOT / "codex-rs/hepta-intelligence-eval/src/product_verification.rs"
    findings.require(
        adapter_path.is_file(),
        "learning_eval_product_verifier",
        "product verification adapter is missing",
    )
    if not lib_path.is_file() or not adapter_path.is_file():
        return
    lib = lib_path.read_text(encoding="utf-8")
    adapter = adapter_path.read_text(encoding="utf-8")
    for token in (
        "mod product_verification;",
        "pub use product_verification::decide_with_signed_evidence_v2;",
    ):
        findings.require(
            token in lib,
            "learning_eval_product_verifier",
            f"learning.eval does not expose the product adapter: {token}",
        )
    findings.require(
        "pub use signed_evaluation::decide_with_signed_evidence_v2;" not in lib,
        "learning_eval_signed_surface",
        "low-level signed evaluator must not be exported directly",
    )
    for token in (
        "pub fn decide_with_signed_evidence_v2",
        "crate::signed_evaluation::decide_with_signed_evidence_v2",
    ):
        findings.require(
            token in adapter,
            "learning_eval_product_verifier",
            f"product verification adapter is missing: {token}",
        )


def verify() -> Any:
    findings = CORE.verify()
    findings.items = [
        finding
        for finding in findings.items
        if not (
            finding.code == "learning_eval_signed_surface"
            and "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;"
            in finding.message
        )
    ]
    _verify_product_evaluation_adapter(findings)
    return findings


def run_self_test() -> list[Any]:
    findings = Findings()
    findings.items.extend(CORE.run_self_test())
    findings.require(
        hashlib.sha256(CORE_PATH.read_bytes()).hexdigest() == CORE_SHA256,
        "self_test_core_digest",
        "Lane E verifier core digest changed",
    )
    findings.require(
        contains_raw_v1_learning_write("let event = LedgerEvent::Decision(value);")
        == ["Decision"],
        "self_test_raw_writer",
        "raw product writer detector missed a constructor",
    )
    findings.require(
        not contains_raw_v1_learning_write(
            "match event { LedgerEvent::Decision(value) => value, _ => todo!() }"
        ),
        "self_test_recovery_reader",
        "recovery-only pattern matching was classified as a writer",
    )
    return findings.items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("verify", "self-test"),
        nargs="?",
        default="verify",
    )
    args = parser.parse_args()
    findings = run_self_test() if args.command == "self-test" else verify().items
    output = {
        "schema": "hepta.lane-e-closure-verification.v1",
        "command": args.command,
        "ok": not findings,
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
