#!/usr/bin/env python3
"""Current closed-world policy for the Lane E verifier.

The v2 verifier remains the compatibility implementation. This module binds it
to the current source graph: the expanded learning.operator contract, Rust test
modules split with ``#[path]``, the registered Agentd objective writer, and
qualification-only legacy write seams that are absent from the default product
feature set.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import hepta_lane_e_closure_v2 as _base

Findings = _base.Findings
WORKFLOW_PATH = _base.WORKFLOW_PATH
ROOT = _base.ROOT
QUALIFICATION_LEGACY_FEATURE = "qualification-legacy-learning-write"
REGISTERED_AGENTD_WRITER = "codex-rs/hepta-agentd/src/objective_ingress.rs"

_base.COVERAGE_TOOL_PIN = "cargo-llvm-cov@0.9.0"
_base.EXPECTED_CASES = {
    *(f"LEDGER-{index:02d}" for index in range(1, 14)),
    *(f"OP-{index:02d}" for index in range(1, 7)),
    *(f"EVAL-{index:02d}" for index in range(1, 8)),
    *(f"ART-{index:02d}" for index in range(1, 13)),
}
_base.EXPECTED_OPERATIONS["learning.operator"] = {
    "build_targets",
    "validate_applicability_certificate",
    "validate_applicability_with_signed_evidence_v2",
    "build_sensor_core",
    "evaluate_bellman_reference",
    "admit_operator_regularity",
    "admit_operator_regularity_with_signed_evidence_v2",
    "fit_transition_model",
    "predict_transition",
    "verify_tabular_operator_plan_v2",
    "fit_tabular_operator_verified_v2",
    "verify_world_model_dataset_v2",
    "fit_transition_model_verified_v2",
}


def _strip_cfg_feature_items(source: str, feature: str) -> str:
    """Remove Rust items disabled unless an explicit non-default feature is set.

    This is intentionally a small, fail-closed source transform for the exact
    qualification seam used by Agentd. It handles one-line imports and balanced
    block items. Unterminated items remain in the returned source and therefore
    continue to trigger the privileged-writer scan.
    """

    marker = f'#[cfg(feature = "{feature}")]'
    lines = source.splitlines(keepends=True)
    retained: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != marker:
            retained.append(lines[index])
            index += 1
            continue

        start = index
        index += 1
        while index < len(lines) and (
            not lines[index].strip() or lines[index].lstrip().startswith("#[")
        ):
            index += 1
        if index >= len(lines):
            retained.extend(lines[start:])
            break

        depth = 0
        saw_block = False
        terminated = False
        while index < len(lines):
            line = lines[index]
            depth += line.count("{") - line.count("}")
            saw_block = saw_block or "{" in line
            index += 1
            if not saw_block and ";" in line:
                terminated = True
                break
            if saw_block and depth <= 0:
                terminated = True
                break
        if not terminated:
            retained.extend(lines[start:])
            break
    return "".join(retained)


def _test_function_exists(path: Path, function: str, visited: set[Path] | None = None) -> bool:
    """Resolve a Rust test in a file or one of its explicit ``#[path]`` modules."""

    if visited is None:
        visited = set()
    path = path.resolve()
    if path in visited or not path.is_file():
        return False
    visited.add(path)
    source = path.read_text(encoding="utf-8")
    if re.search(rf"\bfn\s+{re.escape(function)}\s*\(", source):
        return True
    for relative in re.findall(
        r'#\s*\[\s*path\s*=\s*"([^"]+)"\s*\]\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+[A-Za-z_][A-Za-z0-9_]*\s*;',
        source,
    ):
        candidate = (path.parent / relative).resolve()
        try:
            candidate.relative_to(ROOT.resolve())
        except ValueError:
            continue
        if _test_function_exists(candidate, function, visited):
            return True
    return False


def verify_traceability(
    trace: dict[str, Any],
    modules: dict[str, dict[str, Any]],
    findings: Findings,
) -> None:
    findings.require(
        trace.get("schema") == "hepta.lane-e-test-traceability.v1",
        "trace_schema",
        "unexpected traceability schema",
    )
    raw_cases = trace.get("cases")
    if not isinstance(raw_cases, list):
        findings.add("trace_cases", "traceability cases must be an array")
        return
    cases = {
        item.get("id"): item
        for item in raw_cases
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    findings.require(
        set(cases) == _base.EXPECTED_CASES,
        "case_closed_world",
        "Lane E test case set drifted",
    )
    dossier_cache: dict[Path, str] = {}
    for case_id, case in cases.items():
        module = case.get("module")
        findings.require(
            module in _base.EXPECTED_MODULES,
            "case_module",
            f"{case_id} has invalid module",
        )
        if module in modules:
            dossier = _base.repository_path(
                modules[module].get("dossier"), findings, f"{case_id}.dossier"
            )
            if dossier is not None and dossier.is_file():
                text = dossier_cache.setdefault(
                    dossier, dossier.read_text(encoding="utf-8")
                )
                findings.require(
                    case_id in text,
                    "dossier_case_missing",
                    f"{case_id} absent from {dossier.relative_to(ROOT)}",
                )
        tests = case.get("tests")
        if not isinstance(tests, list) or not tests:
            findings.add("case_tests_missing", f"{case_id} has no native tests")
            continue
        for index, test in enumerate(tests):
            if not isinstance(test, dict):
                findings.add("test_mapping", f"{case_id}.tests[{index}] is invalid")
                continue
            path = _base.repository_path(
                test.get("source"), findings, f"{case_id}.tests[{index}].source"
            )
            function = test.get("function")
            if path is None or not path.is_file() or not isinstance(function, str):
                findings.add("test_mapping", f"{case_id}.tests[{index}] is incomplete")
                continue
            findings.require(
                _test_function_exists(path, function),
                "test_function_unresolved",
                f"{function} absent from {path.relative_to(ROOT)} and explicit path modules",
            )
        findings.require(
            case.get("status") == "native_test_mapped",
            "case_status",
            f"{case_id} is not native_test_mapped",
        )

    for field, expected_count in (("crossCrateCases", 1), ("productBoundaryCases", 1)):
        records = trace.get(field)
        findings.require(
            isinstance(records, list) and len(records) == expected_count,
            "trace_boundary_count",
            f"{field} must contain exactly one record",
        )
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                findings.add("trace_boundary_record", f"invalid record in {field}")
                continue
            path = _base.repository_path(record.get("source"), findings, f"{field}.source")
            function = record.get("function")
            if path is None or not path.is_file() or not isinstance(function, str):
                findings.add("trace_boundary_record", f"incomplete record in {field}")
                continue
            findings.require(
                _test_function_exists(path, function),
                "trace_boundary_function",
                f"{function} absent from {path.relative_to(ROOT)} and explicit path modules",
            )


def verify_product_writer_exclusivity(findings: Findings) -> None:
    manifest_path = ROOT / "codex-rs/hepta-agentd/Cargo.toml"
    findings.require(
        manifest_path.is_file(),
        "agentd_manifest_missing",
        "Agentd manifest is missing",
    )
    manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else ""
    default_match = re.search(r"(?m)^default\s*=\s*\[(?P<features>[^]]*)\]", manifest)
    default_features = default_match.group("features") if default_match else ""
    findings.require(
        QUALIFICATION_LEGACY_FEATURE not in default_features,
        "legacy_learning_write_default_enabled",
        f"{QUALIFICATION_LEGACY_FEATURE} must not be a default Agentd feature",
    )
    findings.require(
        re.search(
            rf"(?m)^{re.escape(QUALIFICATION_LEGACY_FEATURE)}\s*=\s*\[",
            manifest,
        )
        is not None,
        "legacy_learning_write_feature_missing",
        "the explicit qualification-only legacy writer feature is missing",
    )

    registered_path = ROOT / REGISTERED_AGENTD_WRITER
    findings.require(
        registered_path.is_file(),
        "registered_learning_writer_missing",
        f"missing {REGISTERED_AGENTD_WRITER}",
    )
    if registered_path.is_file():
        registered = registered_path.read_text(encoding="utf-8")
        for token in (
            "prepare_intelligence_run_v1(",
            "LedgerWitnessStore",
            "reconcile_witness(",
            "authbus_ingress::require_ready(agentd)?",
            "post-publication signature revalidation",
        ):
            findings.require(
                token in registered,
                "registered_learning_writer_contract",
                f"{REGISTERED_AGENTD_WRITER} lacks {token}",
            )

    allowed = (
        "codex-rs/hepta-learning-ledger/",
        "codex-rs/hepta-shadow-qualification/",
    )
    forbidden = {
        r"\bDurableLearningJournal\b": "legacy durable journal",
        r"LedgerEvent::Decision\b": "raw decision append",
        r"LedgerEvent::Outcome\b": "raw outcome append",
        r"LedgerEvent::Credit\b": "raw credit append",
        r"LedgerEvent::Revocation\b": "raw revocation append",
    }
    for path in (ROOT / "codex-rs").rglob("*.rs"):
        relative = path.relative_to(ROOT).as_posix()
        if (
            relative.startswith(allowed)
            or "/tests/" in relative
            or path.name.endswith(("_tests.rs", "_test_support.rs"))
        ):
            continue
        if relative == REGISTERED_AGENTD_WRITER:
            continue
        text = _strip_cfg_feature_items(
            path.read_text(encoding="utf-8"), QUALIFICATION_LEGACY_FEATURE
        )
        for pattern, description in forbidden.items():
            findings.require(
                re.search(pattern, text) is None,
                "legacy_learning_writer_product_bypass",
                f"{relative} uses {description} outside the registered writer or non-default qualification seam",
            )


def verify_authority_posture(findings: Findings) -> None:
    sources = [
        "codex-rs/hepta-learning-ledger/src/causal_v2.rs",
        "codex-rs/hepta-learning-artifacts/src/closure_v2.rs",
        "codex-rs/hepta-learning-artifacts/src/publication.rs",
        "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
        "codex-rs/hepta-learning-artifacts/src/owner/service_authority.rs",
        "codex-rs/hepta-learning-artifacts/src/sensor_core_registry.rs",
        "codex-rs/hepta-bellman-operator/src/reference.rs",
        "codex-rs/hepta-bellman-operator/src/world_model.rs",
        "codex-rs/hepta-intelligence-eval/src/closure.rs",
    ]
    for relative in sources:
        path = ROOT / relative
        findings.require(path.is_file(), "authority_source_missing", f"missing {relative}")
        if path.is_file():
            findings.require(
                "AuthorityPosture::DENY_ALL" in path.read_text(encoding="utf-8"),
                "deny_all_missing",
                f"{relative} lacks explicit DENY_ALL",
            )


_base.verify_traceability = verify_traceability
_base.verify_product_writer_exclusivity = verify_product_writer_exclusivity
_base.verify_authority_posture = verify_authority_posture

verify_workflows = _base.verify_workflows
main = _base.main
