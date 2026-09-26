#!/usr/bin/env python3
"""Canonical Lane E verifier entrypoint.

The large read-only verifier remains in ``hepta_lane_e_closure_core.py``. This
entrypoint binds its closed-world sets to a versioned data contract and applies
two narrow compatibility adapters:

* the signed-evaluation V2 decision is a public production API now;
* the legacy Agentd V1 writer seam is allowed only behind an explicit,
  non-default, non-workflow qualification feature.

Neither adapter weakens the product scan. Unguarded raw V1 writers, deleted
product sources, default feature activation, and workflow activation remain
hard failures.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts/hepta_lane_e_closure_core.py"
CONTRACT_PATH = ROOT / "qualification/lane-e/CLOSURE_CONTRACT.json"
AGENTD_CARGO_PATH = ROOT / "codex-rs/hepta-agentd/Cargo.toml"


def load_core() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hepta_lane_e_closure_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Lane E verifier core: {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_contract() -> dict[str, Any]:
    value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Lane E closure contract must be a JSON object")
    return value


def contract_cases(contract: dict[str, Any]) -> set[str]:
    ranges = contract.get("caseRanges")
    if not isinstance(ranges, dict):
        raise ValueError("caseRanges must be an object")
    cases: set[str] = set()
    for prefix, bounds in ranges.items():
        if (
            not isinstance(prefix, str)
            or not isinstance(bounds, list)
            or len(bounds) != 2
            or not all(isinstance(value, int) for value in bounds)
        ):
            raise ValueError(f"invalid case range: {prefix!r}={bounds!r}")
        first, last = bounds
        if first <= 0 or last < first:
            raise ValueError(f"invalid case range bounds: {prefix!r}={bounds!r}")
        cases.update(f"{prefix}-{index:02d}" for index in range(first, last + 1))
    return cases


def contract_operations(contract: dict[str, Any]) -> dict[str, set[str]]:
    raw = contract.get("operations")
    if not isinstance(raw, dict):
        raise ValueError("operations must be an object")
    operations: dict[str, set[str]] = {}
    for module, values in raw.items():
        if (
            not isinstance(module, str)
            or not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError(f"invalid operation set for {module!r}")
        operations[module] = set(values)
    return operations


def strip_exact_feature_items(text: str, feature: str) -> str:
    """Remove only Rust items guarded by one exact single-feature cfg."""

    guard = f'#[cfg(feature = "{feature}")]'
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != guard:
            output.append(lines[index])
            index += 1
            continue

        output.append("\n" if lines[index].endswith("\n") else "")
        index += 1
        while index < len(lines) and lines[index].lstrip().startswith("#["):
            output.append("\n" if lines[index].endswith("\n") else "")
            index += 1

        started_block = False
        brace_depth = 0
        while index < len(lines):
            line = lines[index]
            output.append("\n" if line.endswith("\n") else "")
            index += 1

            if not started_block and ";" in line and "{" not in line:
                break

            opens = line.count("{")
            closes = line.count("}")
            if opens:
                started_block = True
            brace_depth += opens - closes
            if started_block and brace_depth <= 0:
                break
    return "".join(output)


def exact_feature_occurrences_are_guarded(text: str, feature: str) -> bool:
    guard = f'#[cfg(feature = "{feature}")]'
    for line in text.splitlines():
        if feature in line and line.strip() != guard:
            return False
    return True


def install_eval_surface_adapter(
    core: ModuleType, contract: dict[str, Any]
) -> Callable[[Any], None]:
    original = core.verify_learning_eval_production_boundary
    legacy_private = (
        "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;"
    )

    def verify(findings: Any) -> None:
        retained = core.Findings()
        original(retained)
        for finding in retained.items:
            if (
                finding.code == "learning_eval_signed_surface"
                and legacy_private in finding.message
            ):
                continue
            findings.items.append(finding)

        lib_path = ROOT / "codex-rs/hepta-intelligence-eval/src/lib.rs"
        cargo_path = ROOT / "codex-rs/hepta-intelligence-eval/Cargo.toml"
        if not lib_path.is_file() or not cargo_path.is_file():
            return
        surface = (
            cargo_path.read_text(encoding="utf-8")
            + "\n"
            + lib_path.read_text(encoding="utf-8")
        )
        tokens = contract.get("signedSurfaceTokens")
        findings.require(
            isinstance(tokens, list)
            and bool(tokens)
            and all(isinstance(token, str) and token for token in tokens),
            "closure_contract_signed_surface",
            "closure contract has an invalid signedSurfaceTokens set",
        )
        if isinstance(tokens, list):
            for token in tokens:
                if isinstance(token, str):
                    findings.require(
                        token in surface,
                        "learning_eval_signed_surface",
                        f"missing required production/compatibility surface token: {token}",
                    )
        findings.require(
            legacy_private not in lib_path.read_text(encoding="utf-8"),
            "learning_eval_signed_surface_ambiguous",
            "signed V2 evaluation must have one public production re-export",
        )

    return verify


def install_writer_exclusivity_adapter(
    core: ModuleType, contract: dict[str, Any]
) -> Callable[[Any], None]:
    feature = contract.get("qualificationOnlyLegacyFeature")
    ledger_feature = contract.get("qualificationOnlyLedgerFeature")
    if not isinstance(feature, str) or not isinstance(ledger_feature, str):
        raise ValueError("qualification feature names must be strings")

    allowed_roots = {
        "codex-rs/hepta-learning-ledger",
        "codex-rs/hepta-shadow-qualification",
    }
    forbidden = {
        r"\bDurableLearningJournal\b": "legacy durable journal trait",
        r"LedgerEvent::Decision\b": "raw V1 Decision append",
        r"LedgerEvent::Outcome\b": "raw V1 Outcome append",
        r"LedgerEvent::Credit\b": "raw V1 Credit append",
        r"LedgerEvent::Revocation\b": "raw V1 Revocation append",
    }

    def verify(findings: Any) -> None:
        deleted = contract.get("deletedLegacyProductSources")
        findings.require(
            isinstance(deleted, list)
            and all(isinstance(path, str) and path for path in deleted),
            "closure_contract_deleted_sources",
            "closure contract has an invalid deletedLegacyProductSources set",
        )
        if isinstance(deleted, list):
            for relative in deleted:
                if isinstance(relative, str):
                    findings.require(
                        not (ROOT / relative).exists(),
                        "legacy_learning_writer_dead_source",
                        f"retired product writer source remains present: {relative}",
                    )

        try:
            cargo = tomllib.loads(AGENTD_CARGO_PATH.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            findings.add(
                "qualification_feature_manifest",
                f"cannot parse Agentd Cargo.toml: {error}",
            )
            cargo = {}
        features = cargo.get("features", {}) if isinstance(cargo, dict) else {}
        default = features.get("default", []) if isinstance(features, dict) else []
        mapping = features.get(feature) if isinstance(features, dict) else None
        findings.require(
            isinstance(default, list) and feature not in default,
            "qualification_feature_default",
            f"{feature} must never be a default Agentd feature",
        )
        findings.require(
            isinstance(mapping, list)
            and f"codex-hepta-learning-ledger/{ledger_feature}" in mapping,
            "qualification_feature_mapping",
            f"{feature} must map explicitly to the ledger qualification feature",
        )

        for workflow in (ROOT / ".github/workflows").glob("*.y*ml"):
            text = workflow.read_text(encoding="utf-8")
            findings.require(
                feature not in text,
                "qualification_feature_workflow",
                f"{workflow.relative_to(ROOT)} activates the legacy writer feature",
            )

        for path in (ROOT / "codex-rs").rglob("*.rs"):
            relative = path.relative_to(ROOT).as_posix()
            if any(
                relative == root or relative.startswith(f"{root}/")
                for root in allowed_roots
            ):
                continue
            if (
                "/tests/" in relative
                or path.name.endswith("_tests.rs")
                or path.name.endswith("_test_support.rs")
            ):
                continue

            source = path.read_text(encoding="utf-8")
            findings.require(
                exact_feature_occurrences_are_guarded(source, feature),
                "qualification_feature_guard",
                f"{relative} references {feature} outside its exact cfg guard",
            )
            product_source = strip_exact_feature_items(source, feature)
            for pattern, description in forbidden.items():
                findings.require(
                    re.search(pattern, product_source) is None,
                    "legacy_learning_writer_product_bypass",
                    f"{relative} uses {description}; product learning writes must use LedgerWriter",
                )

    return verify


def validate_contract(core: ModuleType, contract: dict[str, Any]) -> list[Any]:
    findings = core.Findings()
    findings.require(
        contract.get("schema") == "hepta.lane-e-closure-contract.v2"
        and contract.get("schemaVersion") == 2,
        "closure_contract_schema",
        "unexpected Lane E closure contract schema",
    )
    try:
        cases = contract_cases(contract)
        operations = contract_operations(contract)
    except ValueError as error:
        findings.add("closure_contract_invalid", str(error))
        return findings.items

    findings.require(
        set(operations) == set(core.EXPECTED_MODULES),
        "closure_contract_modules",
        "closure contract operation modules differ from Lane E modules",
    )
    findings.require(
        len(cases) == 38,
        "closure_contract_cases",
        "Lane E closure contract must enumerate 38 unique cases",
    )

    guarded = (
        f'#[cfg(feature = "{contract["qualificationOnlyLegacyFeature"]}")]\n'
        "use example::DurableLearningJournal;\n"
        "fn retained() { let _ = LedgerEvent::Decision(value); }\n"
    )
    filtered = strip_exact_feature_items(
        guarded, str(contract["qualificationOnlyLegacyFeature"])
    )
    findings.require(
        "DurableLearningJournal" not in filtered
        and "LedgerEvent::Decision" in filtered,
        "closure_contract_guard_parser",
        "qualification-only item filtering did not preserve unguarded product code",
    )
    return findings.items


def configure(core: ModuleType, contract: dict[str, Any]) -> None:
    core.EXPECTED_CASES = contract_cases(contract)
    core.EXPECTED_OPERATIONS = contract_operations(contract)
    core.verify_learning_eval_production_boundary = install_eval_surface_adapter(
        core, contract
    )
    core.verify_product_writer_exclusivity = install_writer_exclusivity_adapter(
        core, contract
    )


def main() -> int:
    core = load_core()
    contract = load_contract()
    configure(core, contract)

    command = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if command not in {"verify", "self-test"} or len(sys.argv) > 2:
        print("usage: hepta-lane-e-closure.py [verify|self-test]", file=sys.stderr)
        return 2

    if command == "self-test":
        findings = core.run_self_test() + validate_contract(core, contract)
    else:
        findings = core.verify().items
    output = {
        "schema": "hepta.lane-e-closure-verification.v2",
        "contractSchema": contract.get("schema"),
        "command": command,
        "ok": not findings,
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
