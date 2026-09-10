#!/usr/bin/env python3
"""Closed-world semantic checks for Lane D objective, NDU and control runtime."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]

OBJECTIVE_ROOT = ROOT / "codex-rs/hepta-objective/src"
NDU_ROOT = ROOT / "codex-rs/hepta-ndu/src"
CONTROL_ROOT = ROOT / "codex-rs/hepta-control-plane/src"

MAP_PATHS = (
    "docs/modules/objective.compiler/IMPLEMENTATION_MAP.json",
    "docs/modules/utility.ndu/IMPLEMENTATION_MAP.json",
    "docs/modules/control.runtime/IMPLEMENTATION_MAP.json",
)

LANE_DOCS = (
    "docs/contracts/OBJECTIVE_ERRORS.json",
    "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md",
    "docs/readiness/NDU_SYSTEM_EXECUTION.md",
    "docs/readiness/CONTROL_RUNTIME_EXECUTION.md",
    "docs/readiness/LANE_D_MATURITY.json",
    "docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json",
    "docs/governance/MODULE_IMPLEMENTATION_BASELINE.md",
    "qualification/module-execution-dossiers/detail/objective.compiler.md",
    "qualification/module-execution-dossiers/detail/utility.ndu.md",
    "qualification/module-execution-dossiers/detail/control.runtime.md",
    *MAP_PATHS,
)

ALLOWED_CHANGE_EXACT = {
    *LANE_DOCS,
    "scripts/hepta-lane-d-semantic-conformance.py",
    ".github/workflows/hepta-lane-d-semantic-conformance.yml",
}
ALLOWED_CHANGE_PREFIXES = (
    "codex-rs/hepta-objective/",
    "codex-rs/hepta-ndu/",
    "codex-rs/hepta-control-plane/",
)


class DuplicateKey(ValueError):
    pass


def object_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result


def fail(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_LANE_D: " + message)


def need(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    need(path.is_file(), f"missing JSON file: {relative}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=object_pairs)
    except Exception as exc:
        fail(f"invalid JSON {relative}: {exc}")
    need(isinstance(value, dict), f"JSON root is not an object: {relative}")
    return value


def text(relative: str) -> str:
    path = ROOT / relative
    need(path.is_file(), f"missing file: {relative}")
    return path.read_text(encoding="utf-8")


def source_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.glob("*.rs"))
        if path.is_file()
    )


def find_protocol(protocols: dict[str, Any], protocol_id: str) -> dict[str, Any]:
    rows = protocols.get("protocols")
    need(isinstance(rows, list), "readiness protocol registry has no protocol list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == protocol_id]
    need(len(matches) == 1, f"protocol {protocol_id} is not uniquely registered")
    return matches[0]


def verify_objective() -> None:
    registry = load_json("docs/contracts/OBJECTIVE_ERRORS.json")
    need(registry.get("schema") == "hepta.objective-error-registry.v1", "objective error schema")
    need(registry.get("owner") == "objective.compiler", "objective error owner")
    need(registry.get("authorityDelta") == "none", "objective error authority delta")
    rows = registry.get("errors")
    need(isinstance(rows, list), "objective error rows")
    codes = [row.get("code") for row in rows if isinstance(row, dict)]
    need(codes == [f"OBJ-E00{index}" for index in range(1, 10)], "objective error code closure/order")
    meanings = [row.get("stableMeaning") for row in rows if isinstance(row, dict)]
    need(len(set(meanings)) == 9 and all(meanings), "objective stable meanings are not unique")

    objective_sources = source_text(OBJECTIVE_ROOT)
    for row in rows:
        variants = row.get("rustVariants")
        need(isinstance(variants, list) and variants, f"{row.get('code')} has no Rust variants")
        for variant in variants:
            need(isinstance(variant, str), f"invalid Rust variant in {row.get('code')}")
            tail = variant.rsplit("::", 1)[-1]
            need(tail in objective_sources, f"unmapped objective Rust variant: {variant}")

    error_source = text("codex-rs/hepta-objective/src/error.rs")
    admission_source = text("codex-rs/hepta-objective/src/objective_admission.rs")
    compiler_source = text("codex-rs/hepta-objective/src/compiler.rs")
    compiler_tests = text("codex-rs/hepta-objective/src/compiler_tests.rs")
    need('Self::AbstainUnavailable => "OBJ-E006"' in error_source, "abstain error code")
    need('Self::EmptyDigest(_) => "OBJ-E004"' in error_source, "integrity error code")
    need('Self::InvalidTerminality => "OBJ-E008"' in admission_source, "terminality error code")
    need("MAX_CALLER_ACTIONS_WITHOUT_ABSTAIN" in compiler_source, "reserved abstain slot")
    need("forbidden_actions.iter().any(|id| id == &abstain)" in compiler_source, "abstain prohibition check")
    need("ConfirmationPolicy::NotRequired" in compiler_source, "confirmation-free abstain")
    need("intrinsic_abstain_cannot_be_forbidden" in compiler_tests, "abstain negative fixture")
    need("maximum_caller_set_compiles_to_exactly_128_actions" in compiler_tests, "action ceiling fixture")
    spec = text("docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md")
    need("docs/contracts/OBJECTIVE_ERRORS.json" in spec, "objective spec error registry binding")
    need("O(n C(n))" in spec and "127" in spec and "intrinsic abstain" in spec, "objective spec semantics")


def verify_ndu() -> None:
    protocols = load_json("docs/readiness/PROTOCOLS.json")
    iteration = find_protocol(protocols, "NduIterationReceiptV1")
    convergence = find_protocol(protocols, "NduConvergenceCertificateV1")
    need(iteration.get("owner") == "utility.ndu", "NDU iteration protocol owner")
    need(convergence.get("owner") == "learning.eval", "NDU convergence certificate owner")

    ndu_sources = source_text(NDU_ROOT)
    need("pub struct NduConvergenceCertificate" not in ndu_sources, "NDU self-issued convergence certificate")
    need("pub struct NduSolverIterationReceipt" in ndu_sources, "local solver iteration receipt")
    need("pub struct NduSolverTerminationReceipt" in ndu_sources, "local solver termination receipt")
    need("terminal_residual_raw" in ndu_sources, "terminal residual field")
    need("maximum_residual_raw" in ndu_sources, "maximum residual field")
    preference = text("codex-rs/hepta-ndu/src/preference.rs")
    need(
        "maximum_residual_raw = maximum_residual_raw.max(terminal_residual_raw)" in preference,
        "maximum residual accumulation",
    )
    model = text("codex-rs/hepta-ndu/src/model.rs")
    evaluator = text("codex-rs/hepta-ndu/src/evaluator.rs")
    scoring = text("codex-rs/hepta-ndu/src/scoring.rs")
    protocol = text("codex-rs/hepta-ndu/src/protocol.rs")
    journal = text("codex-rs/hepta-ndu/src/projection_journal.rs")
    need("pub struct EvaluationPolicyV1" in model, "NDU evaluation policy")
    need("pub enum AggregationOperator" in model, "NDU aggregation operators")
    need("pub struct NduEvaluationReceiptV2" in model, "NDU V2 receipt")
    need("pub fn evaluate_candidates_with_policy" in evaluator, "policy-bound evaluator")
    need("legacy-sum-max-zero-tolerance-v1" in evaluator, "named legacy policy")
    need("digest_evaluation_policy" in evaluator, "evaluation policy digest")
    need("tolerances" in scoring and "tolerance_raw" in scoring, "Pareto tolerance use")
    need("pub struct NduIterationContextV1" in protocol, "iteration context")
    need("AuthorityPosture::DENY_ALL" in protocol, "deny-all iteration receipt")
    need("pub struct NduProjectionJournalV1" in journal, "projection journal")
    need("CorruptEntryDigest" in journal and "RevokedProjection" in journal, "projection integrity/revocation")
    spec = text("docs/readiness/NDU_SYSTEM_EXECUTION.md")
    need("NduSolverTerminationReceipt" in spec, "NDU spec local receipt")
    need("learning.eval" in spec and "EvaluationPolicyV1" in spec, "NDU spec ownership/policy")


def verify_control() -> None:
    cargo = text("codex-rs/hepta-control-plane/Cargo.toml")
    need("codex-hepta-ndu" not in cargo, "control runtime directly links NDU implementation")
    planner = text("codex-rs/hepta-control-plane/src/planner.rs")
    journal = text("codex-rs/hepta-control-plane/src/planner_journal.rs")
    for symbol in (
        "pub fn collect_snapshot",
        "pub fn prepare_plan",
        "pub fn bind_ndu_plan_evaluation_v1",
        "pub fn finalize_plan",
        "pub fn request_execution_grants",
    ):
        need(symbol in planner, f"missing control planner symbol: {symbol}")
    for forbidden in ("evaluate_candidates(", "pareto_frontier(", "score_frontier("):
        need(forbidden not in planner, f"control runtime reimplements NDU: {forbidden}")
    need(planner.count("AuthorityPosture::DENY_ALL") >= 4, "control deny-all receipts")
    need("MissingResourceAxis" in planner, "missing resource is unavailable")
    need("resource_rejected_candidate_ids" in planner, "resource-floor rejection evidence")
    need("EvaluationCandidateSetMismatch" in planner, "complete NDU candidate binding")
    need("pub struct PlannerJournalV1" in journal, "planner journal")
    need("CorruptEntryDigest" in journal and "RevokedPlan" in journal, "planner integrity/revocation")
    spec = text("docs/readiness/CONTROL_RUNTIME_EXECUTION.md")
    for marker in (
        "prepare_plan",
        "bind_ndu_plan_evaluation_v1",
        "finalize_plan",
        "GrantRequestSetV1",
        "AuthorityPosture::DENY_ALL",
    ):
        need(marker in spec, f"control execution spec missing {marker}")


def verify_implementation_maps() -> None:
    for relative in MAP_PATHS:
        mapping = load_json(relative)
        need(mapping.get("schema") == "hepta.module-implementation-map.v1", f"map schema: {relative}")
        need(mapping.get("authorityDelta") == "none", f"map authority delta: {relative}")
        operations = mapping.get("operations")
        need(isinstance(operations, list) and operations, f"empty operations: {relative}")
        names: set[str] = set()
        for operation in operations:
            need(isinstance(operation, dict), f"invalid operation row: {relative}")
            name = operation.get("operation")
            need(isinstance(name, str) and name not in names, f"duplicate/invalid operation: {relative}")
            names.add(name)
            source_path = operation.get("sourcePath")
            symbol = operation.get("nativeSymbol")
            need(isinstance(source_path, str), f"missing source path: {relative}/{name}")
            need(isinstance(symbol, str), f"missing native symbol: {relative}/{name}")
            source = text(source_path)
            tail = symbol.rsplit("::", 1)[-1]
            need(tail in source, f"native symbol not found: {symbol}")
            tests = operation.get("tests")
            need(isinstance(tests, list) and tests, f"operation has no tests: {relative}/{name}")
            for test in tests:
                need(isinstance(test, dict), f"invalid test row: {relative}/{name}")
                test_path = test.get("path")
                test_symbol = test.get("symbol")
                need(isinstance(test_path, str), f"missing test path: {relative}/{name}")
                need(isinstance(test_symbol, str) and test_symbol, f"missing test symbol: {relative}/{name}")
                test_source = text(test_path)
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", test_symbol):
                    need(f"fn {test_symbol}" in test_source, f"test symbol not found: {test_symbol}")


def verify_maturity_and_ownership() -> None:
    maturity = load_json("docs/readiness/LANE_D_MATURITY.json")
    need(maturity.get("lane") == "LANE-D-OBJECTIVE-VALUE", "maturity lane")
    need(maturity.get("authorityDelta") == "none", "maturity authority delta")
    modules = maturity.get("modules")
    need(isinstance(modules, list) and len(modules) == 3, "maturity module closure")
    need(
        {module.get("module") for module in modules if isinstance(module, dict)}
        == {"objective.compiler", "utility.ndu", "control.runtime"},
        "maturity module identities",
    )
    for module in modules:
        dimensions = module.get("dimensions")
        need(isinstance(dimensions, dict), f"missing maturity dimensions: {module.get('module')}")
        for external in ("productCaller", "independentAcceptance", "activation", "release"):
            state = dimensions.get(external, {}).get("state")
            need(state == "not_established", f"unsupported positive maturity: {module.get('module')}/{external}")

    overlay = load_json("docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json")
    need(overlay.get("authorityDelta") == "none", "work-package overlay authority")
    legacy = overlay.get("legacyPackageDisposition")
    need(isinstance(legacy, dict) and legacy.get("sourceMutationAllowed") is False, "legacy NDU-2 mutation disabled")
    packages = overlay.get("packages")
    need(isinstance(packages, list) and len(packages) == 3, "owner-safe package closure")
    package_map = {package.get("id"): package for package in packages if isinstance(package, dict)}
    need(set(package_map) == {
        "NDU-2A-HIERARCHY-PROTOCOLS",
        "NDU-2B-NDU-HIERARCHY-IMPLEMENTATION",
        "RCP-2-NDU-HIERARCHY-INTEGRATION",
    }, "owner-safe package IDs")
    ndu_paths = package_map["NDU-2B-NDU-HIERARCHY-IMPLEMENTATION"].get("allowedWritePaths", [])
    rcp_paths = package_map["RCP-2-NDU-HIERARCHY-INTEGRATION"].get("allowedWritePaths", [])
    need("codex-rs/hepta-ndu/**" in ndu_paths, "NDU owner path")
    need("codex-rs/hepta-control-plane/**" not in ndu_paths, "NDU package foreign control path")
    need("codex-rs/hepta-control-plane/**" in rcp_paths, "RCP owner path")
    need("codex-rs/hepta-ndu/**" not in rcp_paths, "RCP package foreign NDU path")
    for package in packages:
        need(package.get("sourceMutationAllowed") is True, f"inactive overlay package: {package.get('id')}")


def verify_documents() -> None:
    unresolved = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE)
    for relative in LANE_DOCS:
        body = text(relative)
        need(not unresolved.search(body), f"unresolved marker in {relative}")
    for relative in (
        "qualification/module-execution-dossiers/detail/objective.compiler.md",
        "qualification/module-execution-dossiers/detail/utility.ndu.md",
        "qualification/module-execution-dossiers/detail/control.runtime.md",
    ):
        body = text(relative)
        need("specified target, not implemented" not in body, f"stale dossier status: {relative}")
        need("IMPLEMENTATION_MAP.json" in body, f"dossier lacks implementation map: {relative}")


def is_allowed_change(path: str) -> bool:
    return path in ALLOWED_CHANGE_EXACT or path.startswith(ALLOWED_CHANGE_PREFIXES)


def verify_changes(base: str) -> None:
    need(bool(re.fullmatch(r"[0-9a-fA-F]{7,40}", base)), "invalid base SHA")
    try:
        output = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        fail("cannot compute change set: " + exc.output.strip())
    changed = {line.strip() for line in output.splitlines() if line.strip()}
    need(changed, "empty Lane D change set")
    unexpected = sorted(path for path in changed if not is_allowed_change(path))
    need(not unexpected, "unexpected paths: " + ", ".join(unexpected))

    requirements: list[tuple[str, Callable[[str], bool], set[str]]] = [
        (
            "objective source",
            lambda path: path.startswith("codex-rs/hepta-objective/"),
            {
                "docs/contracts/OBJECTIVE_ERRORS.json",
                "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md",
                "docs/modules/objective.compiler/IMPLEMENTATION_MAP.json",
                "qualification/module-execution-dossiers/detail/objective.compiler.md",
            },
        ),
        (
            "NDU source",
            lambda path: path.startswith("codex-rs/hepta-ndu/"),
            {
                "docs/readiness/NDU_SYSTEM_EXECUTION.md",
                "docs/modules/utility.ndu/IMPLEMENTATION_MAP.json",
                "qualification/module-execution-dossiers/detail/utility.ndu.md",
            },
        ),
        (
            "control source",
            lambda path: path.startswith("codex-rs/hepta-control-plane/"),
            {
                "docs/readiness/CONTROL_RUNTIME_EXECUTION.md",
                "docs/modules/control.runtime/IMPLEMENTATION_MAP.json",
                "qualification/module-execution-dossiers/detail/control.runtime.md",
            },
        ),
    ]
    for label, selector, required in requirements:
        if any(selector(path) for path in changed):
            missing = sorted(required - changed)
            need(not missing, f"{label} changed without: {', '.join(missing)}")

    if any(path.startswith(ALLOWED_CHANGE_PREFIXES) for path in changed):
        required_global = {
            "docs/readiness/LANE_D_MATURITY.json",
            "docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json",
            "scripts/hepta-lane-d-semantic-conformance.py",
            ".github/workflows/hepta-lane-d-semantic-conformance.yml",
        }
        missing = sorted(required_global - changed)
        need(not missing, "Lane D source changed without global closure files: " + ", ".join(missing))


def verify() -> None:
    verify_objective()
    verify_ndu()
    verify_control()
    verify_implementation_maps()
    verify_maturity_and_ownership()
    verify_documents()
    print(json.dumps({
        "status": "PASS_HEPTA_LANE_D_SEMANTIC_CONFORMANCE",
        "modules": ["objective.compiler", "utility.ndu", "control.runtime"],
        "implementationMaps": 3,
        "authorityGranted": False,
    }, sort_keys=True))


def self_test() -> None:
    try:
        json.loads('{"a":1,"a":2}', object_pairs_hook=object_pairs)
        fail("duplicate-key fixture was accepted")
    except DuplicateKey:
        pass
    need(is_allowed_change("codex-rs/hepta-ndu/src/lib.rs"), "source allow fixture")
    need(is_allowed_change("docs/readiness/CONTROL_RUNTIME_EXECUTION.md"), "exact allow fixture")
    need(not is_allowed_change("codex-rs/hepta-agentd/src/lib.rs"), "foreign path fixture")
    print(json.dumps({
        "status": "PASS_HEPTA_LANE_D_SEMANTIC_SELF_TEST",
        "cases": ["duplicate_key", "allowed_source", "allowed_document", "foreign_path"],
        "authorityGranted": False,
    }, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify")
    subparsers.add_parser("self-test")
    changes = subparsers.add_parser("verify-changes")
    changes.add_argument("--base", required=True)
    args = parser.parse_args()
    if args.command == "verify":
        verify()
    elif args.command == "self-test":
        self_test()
    else:
        verify_changes(args.base)
        print(json.dumps({
            "status": "PASS_HEPTA_LANE_D_CHANGE_POLICY",
            "base": args.base,
            "authorityGranted": False,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
