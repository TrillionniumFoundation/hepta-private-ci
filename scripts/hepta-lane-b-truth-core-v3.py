#!/usr/bin/env python3
"""Fail-closed verifier for the exact Lane B repository candidate.

This verifier establishes only repository-controlled source identity, module and
operation coverage, current native anchors, generated module projections and
test traceability. It never upgrades those facts into deployment, remote effect,
real model/device execution, independent acceptance, promotion or release.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "qualification/lane-b/LANE_B_CANDIDATE_MANIFEST.json"
TRUTH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"
TRACE = ROOT / "qualification/lane-b/LANE_B_TEST_TRACEABILITY.json"
SOURCE_BINDINGS = ROOT / "docs/modules/SOURCE_BINDINGS.json"
WORKFLOW = ROOT / ".github/workflows/hepta-lane-b-truth.yml"

MODULES = [
    "runtime.supervisor", "runtime.fleet", "runtime.agentd", "runtime.codex",
    "inference.control", "inference.worker", "automation.taskflow",
    "channel.matrix", "browser.servo", "ui.control", "ui.native",
]
OPERATIONS = {
    "runtime.supervisor": ["start_instance", "observe_health", "drain", "load_next"],
    "runtime.fleet": ["admit_host", "allocate", "renew_or_revoke"],
    "runtime.agentd": ["compose_runtime", "start_run", "cancel_run", "attach_context"],
    "runtime.codex": ["open_thread", "submit_turn", "dispatch_tool", "observe_delivery"],
    "inference.control": ["reserve_request", "schedule", "cancel", "settle"],
    "inference.worker": ["load_model", "run", "unload"],
    "automation.taskflow": ["register_schedule", "materialize_due", "claim_occurrence", "execute_step"],
    "channel.matrix": ["admit_event", "prepare_send", "observe_send"],
    "browser.servo": ["open_profile", "observe_page", "navigate_or_act"],
    "ui.control": ["read_view", "submit_request", "request_stop"],
    "ui.native": ["connect_runtime", "render_runtime_view", "request_platform_capability", "apply_shell_update"],
}
ALLOWED_STATES = {"implemented", "implemented_partial", "boundary_only", "delegated_partial"}
HEX40 = re.compile(r"[0-9a-f]{40}")
FORBIDDEN_WORKFLOW = ("contents: write", "pull-requests: write", "issues: write", "actions: write", "git push")


class Invalid(ValueError):
    pass


def need(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise Invalid(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        raise Invalid(f"{path.relative_to(ROOT)}: {exc}") from exc
    need(isinstance(value, dict), f"{path.relative_to(ROOT)} root object")
    return value


def git(*args: str) -> str:
    process = subprocess.run(["git", *args], cwd=ROOT, check=False, capture_output=True, text=True)
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise Invalid(f"git {' '.join(args)} failed: {detail}")
    return process.stdout.strip()


def current_head() -> str:
    head = git("rev-parse", "HEAD")
    need(bool(HEX40.fullmatch(head)), "HEAD shape")
    expected = os.environ.get("EXPECTED_SHA")
    if expected:
        need(head == expected, f"HEAD {head} != EXPECTED_SHA {expected}")
    return head


def verify_manifest(manifest: dict[str, Any]) -> tuple[str, str, list[str]]:
    need(manifest.get("schema") == "hepta.lane-b-candidate-manifest.v3", "manifest schema")
    need(manifest.get("schemaVersion") == 3, "manifest version")
    need(manifest.get("repository") == "TrillionniumFoundation/hepta-private-ci", "repository")
    need(manifest.get("laneId") == "LANE-B-RUNTIME", "lane")
    need(manifest.get("requiredModuleGuides") == MODULES, "manifest module order")
    need(manifest.get("requiredOperationCount") == 39, "manifest operation count")
    need("candidateHead" not in manifest, "self-referential candidateHead is forbidden")

    anchor = manifest.get("lineageAnchor")
    need(isinstance(anchor, dict), "lineage anchor")
    commit, tree = anchor.get("commit"), anchor.get("tree")
    need(isinstance(commit, str) and bool(HEX40.fullmatch(commit)), "anchor commit")
    need(isinstance(tree, str) and bool(HEX40.fullmatch(tree)), "anchor tree")
    need(git("rev-parse", f"{commit}^{{tree}}") == tree, "anchor tree mismatch")
    head = current_head()
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", commit, head], cwd=ROOT, check=False)
    need(ancestor.returncode == 0, "lineage anchor is not an ancestor of HEAD")

    prefixes = manifest.get("allowedPathPrefixes")
    need(isinstance(prefixes, list) and prefixes and all(isinstance(x, str) and x for x in prefixes), "path envelope")
    changed = [x for x in git("diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{commit}..HEAD").splitlines() if x]
    need(changed, "candidate has no changes after lineage anchor")
    denied = [path for path in changed if not any(path.startswith(prefix) for prefix in prefixes)]
    need(not denied, "path outside Lane B envelope: " + ", ".join(denied))
    for path in changed:
        if path.startswith(".github/workflows/hepta-lane-b-"):
            text = (ROOT / path).read_text(encoding="utf-8").lower()
            for forbidden in FORBIDDEN_WORKFLOW:
                need(forbidden not in text, f"{path}: forbidden capability {forbidden}")
            need("persist-credentials: false" in text, f"{path}: checkout credentials persist")

    claims = manifest.get("claimBoundary")
    need(isinstance(claims, dict), "manifest claim boundary")
    need(claims.get("repositoryControlledDocumentationAndMappingMayBeCertified") is True, "repository claim")
    for key, value in claims.items():
        if key.endswith("MayBeSelfCertified"):
            need(value is False, f"unsupported self-certification: {key}")
    return commit, tree, changed


def verify_mapping(module: str, mapping: dict[str, Any], roots: list[str]) -> None:
    need(set(mapping) == {"path", "symbol", "callerClass", "buildTarget"}, f"{module}: mapping fields")
    path, symbol = mapping.get("path"), mapping.get("symbol")
    need(isinstance(path, str) and path, f"{module}: path")
    need(isinstance(symbol, str) and len(symbol) >= 5, f"{module}: symbol")
    need(isinstance(mapping.get("callerClass"), str) and mapping["callerClass"], f"{module}: caller class")
    need(isinstance(mapping.get("buildTarget"), str) and mapping["buildTarget"], f"{module}: build target")
    need(any(path == root or path.startswith(root + "/") for root in roots), f"{module}: source outside implementation roots: {path}")
    source = ROOT / path
    need(source.is_file(), f"{module}: missing source {path}")
    need(symbol in source.read_text(encoding="utf-8"), f"{module}: missing symbol {symbol!r} in {path}")
    need("/tests/" not in path and not path.endswith("_tests.rs") and not path.endswith(".test.js"), f"{module}: test-only mapping")


def map_projection(truth: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "hepta.lane-b-module-implementation-map.v2",
        "schemaVersion": 2,
        "laneId": "LANE-B-RUNTIME",
        "module": row["module"],
        "sourceOfTruth": "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json",
        "lineageAnchor": {"commit": truth["lineageAnchor"]["commit"], "tree": truth["lineageAnchor"]["tree"]},
        "maturity": row["maturity"],
        "ownerRoots": row["ownerRoots"],
        "implementationRoots": row["implementationRoots"],
        "aliasResolution": row["aliasResolution"],
        "operations": [
            {
                "designOperation": operation["designOperation"],
                "state": operation["state"],
                "ownerEntrypoint": operation["ownerEntrypoint"],
                "delegatedCallee": operation["delegatedCallee"],
                "testIds": operation["testIds"],
            }
            for operation in row["operations"]
        ],
        "productionCallerState": row["productionCallerState"],
        "productExecutionState": row["productExecutionState"],
        "externalGaps": [gap["gap"] for gap in row["residualGaps"]],
        "generatedProjection": True,
    }


def verify_truth(truth: dict[str, Any], trace: dict[str, Any], manifest: dict[str, Any]) -> dict[str, int]:
    need(truth.get("schema") == "hepta.lane-b-implementation-truth.v3", "truth schema")
    need(truth.get("schemaVersion") == 3, "truth version")
    need(truth.get("moduleOrder") == MODULES, "truth module order")
    need(truth.get("operationCount") == 39, "truth operation count")
    need("currentMappingDebtClosed" not in truth.get("claimBoundary", {}), "ambiguous old closure flag")
    need(truth.get("lineageAnchor", {}).get("commit") == manifest["lineageAnchor"]["commit"], "truth anchor commit")
    need(truth.get("lineageAnchor", {}).get("tree") == manifest["lineageAnchor"]["tree"], "truth anchor tree")

    claims = truth.get("claimBoundary")
    need(isinstance(claims, dict), "truth claim boundary")
    for key in ("documentationStructureComplete", "laneModuleSetComplete", "allDesignOperationsDispositioned", "repositoryControlledOperationMappingClosed", "nativeSourceAnchorsComplete", "testTraceabilitySpecified"):
        need(claims.get(key) is True, f"missing repository closure {key}")
    for key in ("targetDesignImplementationClosed", "productionConsumerCallsitesProved", "productExecutionProved", "deploymentProved", "independentAcceptanceProved", "externalEffectsProved", "hardwareEvidenceProved", "futureWindowEfficacyProved"):
        need(claims.get(key) is False, f"unsupported positive claim {key}")

    need(trace.get("schema") == "hepta.lane-b-test-traceability.v2", "trace schema")
    need(trace.get("schemaVersion") == 2, "trace version")
    need(trace.get("lineageAnchor", {}).get("commit") == truth["lineageAnchor"]["commit"], "trace anchor")
    suites = trace.get("suites")
    need(isinstance(suites, list), "trace suites")
    suite_by_module = {suite.get("module"): suite for suite in suites if isinstance(suite, dict)}
    need(set(suite_by_module) == set(MODULES), "one trace suite per module")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for suite in suites:
        need(suite.get("externalCompletionRequired") is True, f"{suite.get('id')}: external boundary")
        command = suite.get("command")
        need(isinstance(command, str) and command in workflow, f"workflow missing command {command}")
        for path in suite.get("paths", []):
            need((ROOT / path).exists(), f"trace path missing {path}")

    source_rows = load(SOURCE_BINDINGS).get("bindings")
    need(isinstance(source_rows, list), "source binding rows")
    source_map = {row.get("module"): row for row in source_rows if isinstance(row, dict)}
    rows = truth.get("modules")
    need(isinstance(rows, list) and [row.get("module") for row in rows] == MODULES, "truth closed module set")
    row_by_module = {row["module"]: row for row in rows}
    counts = {state: 0 for state in ALLOWED_STATES}
    total = 0
    operation_cases = trace.get("operationCases")
    cases_by_module = trace.get("casesByModule")
    need(isinstance(operation_cases, dict) and isinstance(cases_by_module, dict), "trace operation cases")

    for row in rows:
        module = row["module"]
        owner_roots = row.get("ownerRoots")
        implementation_roots = row.get("implementationRoots")
        need(isinstance(owner_roots, list) and owner_roots, f"{module}: owner roots")
        need(isinstance(implementation_roots, list) and implementation_roots, f"{module}: implementation roots")
        need(source_map.get(module, {}).get("declaredRoots") == owner_roots, f"{module}: canonical owner root drift")
        for root in implementation_roots:
            need((ROOT / root).exists(), f"{module}: missing implementation root {root}")
        aliases = row.get("aliasResolution")
        need(isinstance(aliases, list), f"{module}: alias resolution")
        if implementation_roots != owner_roots:
            need(aliases, f"{module}: implementation roots differ without alias resolution")

        operations = row.get("operations")
        need(isinstance(operations, list), f"{module}: operations")
        need([operation.get("designOperation") for operation in operations] == OPERATIONS[module], f"{module}: operation order")
        for operation in operations:
            total += 1
            state = operation.get("state")
            need(state in ALLOWED_STATES, f"{module}: operation state {state}")
            counts[state] += 1
            owner = operation.get("ownerEntrypoint")
            delegated = operation.get("delegatedCallee")
            if state == "delegated_partial":
                need(owner is None and isinstance(delegated, dict), f"{module}: delegated operation shape")
            else:
                need(isinstance(owner, dict), f"{module}: owner entrypoint required")
                verify_mapping(module, owner, implementation_roots)
            if delegated is not None:
                need(isinstance(delegated, dict), f"{module}: delegated mapping")
                callee = delegated.get("module")
                need(callee in row_by_module, f"{module}: unknown delegated module {callee}")
                verify_mapping(callee, {key: delegated[key] for key in ("path", "symbol", "callerClass", "buildTarget")}, row_by_module[callee]["implementationRoots"])
            tests = operation.get("testIds")
            need(isinstance(tests, list) and tests and all(isinstance(x, str) and x for x in tests), f"{module}: test IDs")
            key = f"{module}/{operation['designOperation']}"
            need(operation_cases.get(key) == tests, f"{key}: trace drift")
            module_cases = cases_by_module.get(module)
            need(isinstance(module_cases, list) and set(tests) <= set(module_cases), f"{key}: unknown case")

        need(row.get("productionCallerState") == "unproved", f"{module}: product caller overclaim")
        need(row.get("productExecutionState") == "unproved", f"{module}: product execution overclaim")
        gaps = row.get("residualGaps")
        need(isinstance(gaps, list) and gaps, f"{module}: residual gaps")
        for gap in gaps:
            need(set(gap) == {"class", "gap"}, f"{module}: gap shape")
            need(gap["class"] == "external_evidence", f"{module}: repository-controlled gap remains: {gap['gap']}")
            need(isinstance(gap["gap"], str) and len(gap["gap"]) >= 30, f"{module}: gap detail")

        map_path = ROOT / f"docs/modules/{module}/IMPLEMENTATION_MAP.json"
        need(map_path.is_file(), f"{module}: implementation map missing")
        need(load(map_path) == map_projection(truth, row), f"{module}: implementation map drift")
        guide = ROOT / f"docs/modules/{module}/TECHNICAL.md"
        dossier = ROOT / f"qualification/module-execution-dossiers/detail/{module}.md"
        need(guide.is_file() and dossier.is_file(), f"{module}: technical documents")

    need(total == 39, "39 operation closed set")
    need(counts["implemented"] == 26, "implemented count")
    need(counts["implemented_partial"] == 10, "implemented_partial count")
    need(counts["delegated_partial"] == 3, "delegated_partial count")
    need(counts["boundary_only"] == 0, "unexpected boundary-only operation")
    return counts


def verify() -> int:
    manifest, truth, trace = load(MANIFEST), load(TRUTH), load(TRACE)
    _, _, changed = verify_manifest(manifest)
    counts = verify_truth(truth, trace, manifest)
    need(not git("status", "--porcelain", "--untracked-files=no"), "tracked tree is dirty")
    print(json.dumps({
        "status": "PASS_HEPTA_LANE_B_REPOSITORY_CLOSURE",
        "head": current_head(),
        "changedPaths": len(changed),
        "modules": 11,
        "operations": 39,
        "states": counts,
        "repositoryControlledGapsOpen": 0,
        "externalEvidenceGatesRetained": True,
        "targetDesignImplementationClosed": False,
        "productExecutionProved": False,
        "independentAcceptanceProved": False,
    }, sort_keys=True))
    return 0


def self_test() -> int:
    need(pairs([("a", 1), ("b", 2)]) == {"a": 1, "b": 2}, "pairs")
    try:
        pairs([("a", 1), ("a", 2)])
    except Invalid:
        pass
    else:
        raise Invalid("duplicate key self-test")
    need(len(MODULES) == 11 and sum(map(len, OPERATIONS.values())) == 39, "closed sets")
    need("delegated_partial" in ALLOWED_STATES, "delegation state")
    print(json.dumps({"status": "PASS_HEPTA_LANE_B_TRUTH_SELF_TEST", "modules": 11, "operations": 39}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "self-test"])
    args = parser.parse_args()
    try:
        return verify() if args.command == "verify" else self_test()
    except Invalid as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_REPOSITORY_CLOSURE: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
