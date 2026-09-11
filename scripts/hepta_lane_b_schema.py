#!/usr/bin/env python3
"""Single fail-closed v3 verifier for the Lane B repository truth bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "qualification/lane-b/LANE_B_CANDIDATE_MANIFEST.json"
TRUTH_PATH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"

MODULES = [
    "runtime.supervisor", "runtime.fleet", "runtime.agentd", "runtime.codex",
    "inference.control", "inference.worker", "automation.taskflow",
    "channel.matrix", "browser.servo", "ui.control", "ui.native",
]
EXPECTED_OPERATIONS = {
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
EXTERNAL_GATES = [f"RDY-EXT-{n:03d}" for n in range(1, 10)]
FORBIDDEN = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE)
TECHNICAL_HEADINGS = [
    "## 1. Identity, mission and ownership", "## 2. Source binding and implementation status",
    "## 3. Boundary, responsibilities and non-goals", "## 5. Contracts, ports and compatibility",
    "## 6. Data authority, persistence and migrations", "## 7. Runtime, concurrency and transaction model",
    "## 8. Failure semantics, recovery and rollback", "## 9. Security, privacy and threat controls",
    "## 10. Performance, capacity and hot-path policy", "## 11. Observability and operations",
    "## 12. Verification and qualification", "## 13. Implementation sequence and work packages",
    "## 14. Activation, compatibility and retirement", "## 15. Definition of module completion",
    "## 16. V8.2 pre-coding implementation-readiness overlay",
]
DOSSIER_HEADINGS = [
    "## 1. Source and work envelope", "## 2. Public operations and contract details",
    "## 3. State records and transaction design", "## 4. Deterministic algorithm and scheduling",
    "## 5. Capacity and performance profile", "## 6. Concrete verification cases",
    "## 7. Integration, rollback and capability ceiling",
]
COMPOSITION_HEADINGS = [
    "## 1. Purpose and truth boundary", "## 2. Canonical module set",
    "## 3. Runtime and process topology", "## 4. Identity tuple", "## 5. Startup order",
    "## 6. Normal request path", "## 7. Automation path", "## 8. Matrix path",
    "## 9. Browser path", "## 10. UI path", "## 11. Cancellation and deadline semantics",
    "## 12. Backpressure and resource exhaustion", "## 13. Fault-state matrix",
    "## 14. Shutdown and rollback order", "## 15. Module maturity at the base",
    "## 16. Evidence package required for activation", "## 17. Acceptance rule",
]
GENERATED_DOCS = [
    "qualification/lane-b/README.md", "qualification/lane-b/STATUS.md",
    "qualification/lane-b/LANE_B_NATIVE_CLOSURE.md", "qualification/lane-b/NATIVE_BINDINGS.json",
]


class Invalid(ValueError):
    pass


def need(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise Invalid(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        raise Invalid(f"{path.relative_to(ROOT)}: {exc}") from exc
    need(isinstance(value, dict), f"{path.relative_to(ROOT)} root")
    return value


def run_git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=ROOT, check=False, capture_output=True, text=True)
    if proc.returncode:
        raise Invalid(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def path_allowed(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def path_inside(path: str, roots: list[str]) -> bool:
    return any(path == root or path.startswith(root + "/") for root in roots)


def symbol_occurrences(text: str, symbol: str) -> int:
    count = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith(symbol):
            continue
        if symbol and (symbol[-1].isalnum() or symbol[-1] == "_") and len(stripped) > len(symbol):
            if stripped[len(symbol)].isalnum() or stripped[len(symbol)] == "_":
                continue
        count += 1
    return count


def truth_digest() -> str:
    return hashlib.sha256(TRUTH_PATH.read_bytes()).hexdigest()


def load_bundle() -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    index = load_json(TRUTH_PATH)
    return {
        "manifest": manifest,
        "index": index,
        "modules": [load_json(ROOT / p) for p in index.get("moduleMapPaths", [])],
        "tests": load_json(ROOT / index.get("testTraceabilityPath", "missing")),
        "gaps": load_json(ROOT / index.get("gapLedgerPath", "missing")),
        "external": load_json(ROOT / index.get("externalGateHandoffPath", "missing")),
    }


def same_subject(value: Any, expected: dict[str, Any], label: str) -> None:
    need(value == expected, f"{label} source subject")


def verify_anchor(module: str, operation: str, anchor: Any, roots: list[str], label: str) -> None:
    need(isinstance(anchor, dict), f"{module}/{operation} {label}")
    allowed = {"path", "symbol", "buildTarget"} | ({"module"} if label == "callee" else set())
    need(set(anchor) == allowed, f"{module}/{operation} {label} fields")
    path, symbol, target = anchor.get("path"), anchor.get("symbol"), anchor.get("buildTarget")
    need(isinstance(path, str) and path_inside(path, roots), f"{module}/{operation} {label} root")
    need(isinstance(symbol, str) and len(symbol) >= 6, f"{module}/{operation} {label} symbol")
    need(isinstance(target, str) and target, f"{module}/{operation} {label} target")
    source = ROOT / path
    need(source.is_file(), f"{module}/{operation} missing {path}")
    need(not path.endswith("_tests.rs") and "/tests/" not in path and "/test/" not in path,
         f"{module}/{operation} test-only mapping")
    need(symbol_occurrences(source.read_text(encoding="utf-8"), symbol) == 1,
         f"{module}/{operation} {label} anchor is missing or non-unique")


def verify_document(path: Path, title: str, headings: list[str], module: str) -> None:
    need(path.is_file(), f"missing {path.relative_to(ROOT)}")
    text = path.read_text(encoding="utf-8")
    need(text.startswith(title + "\n"), f"{path.relative_to(ROOT)} title")
    need(not FORBIDDEN.search(text), f"{path.relative_to(ROOT)} unresolved marker")
    positions = [text.find(h) for h in headings]
    need(all(p >= 0 for p in positions) and positions == sorted(positions),
         f"{path.relative_to(ROOT)} sections")
    need(module in text, f"{path.relative_to(ROOT)} module")


def verify_structure(bundle: dict[str, Any], *, inspect_source: bool) -> tuple[int, int]:
    manifest, index = bundle["manifest"], bundle["index"]
    modules, tests, gaps, external = bundle["modules"], bundle["tests"], bundle["gaps"], bundle["external"]
    need((manifest.get("schema"), manifest.get("schemaVersion")) ==
         ("hepta.lane-b-candidate-manifest.v3", 3), "manifest schema")
    need((index.get("schema"), index.get("schemaVersion")) ==
         ("hepta.lane-b-implementation-truth-index.v3", 3), "truth schema")
    for key in ("planId", "planVersion", "laneId"):
        need(index.get(key) == manifest.get(key), f"manifest/index {key}")
    need(manifest.get("repository") == "TrillionniumFoundation/hepta-private-ci", "repository")
    need(manifest.get("requiredModuleGuides") == MODULES, "manifest modules")
    need(index.get("moduleOrder") == MODULES, "truth modules")
    need((index.get("operationCount"), index.get("acceptanceTestCount")) == (39, 44), "truth counts")
    need(len(modules) == 11 and len(index.get("moduleMapPaths", [])) == 11, "module maps")
    subject = index.get("sourceSubject")
    need(isinstance(subject, dict), "source subject")
    for a, b in (("repository", "repository"), ("baseBranch", "baseBranch"),
                 ("baseCommit", "baseCommit"), ("baseTree", "baseTree"),
                 ("candidateBranch", "candidateBranch")):
        need(subject.get(a) == manifest.get(b), f"source {a}")
    repo = index.get("closureModel", {}).get("repositoryControlled", {})
    need(repo.get("repositoryControlledBlockersClosed") is True and
         repo.get("repositoryControlledGapCountOpen") == 0, "repository closure")
    need(all(v is False for v in index.get("closureModel", {}).get("separatelyGovernedEvidence", {}).values()),
         "unsupported external claim")
    for label, value in (("tests", tests), ("gaps", gaps), ("external", external)):
        same_subject(value.get("sourceSubject"), subject, label)

    need((tests.get("schema"), tests.get("schemaVersion")) ==
         ("hepta.lane-b-test-traceability.v2", 2), "test schema")
    need((tests.get("caseCount"), tests.get("operationCount")) == (44, 39), "test counts")
    need(tests.get("exactSourceRequired") is True and tests.get("syntheticMergeRequired") is True,
         "test source modes")
    commands = tests.get("commandsByModule")
    need(isinstance(commands, dict) and list(commands) == MODULES and all(commands[m] for m in MODULES),
         "test commands")
    cases = tests.get("cases")
    need(isinstance(cases, list) and len(cases) == 44, "test cases")
    ids = [c.get("id") for c in cases]
    need(len(set(ids)) == 44, "duplicate test ids")
    tests_by_module = {m: set() for m in MODULES}
    case_operations: set[str] = set()
    for case in cases:
        module = case.get("module")
        need(module in tests_by_module and case.get("operations"), f"bad test {case.get('id')}")
        tests_by_module[module].add(case["id"])
        case_operations.update(case["operations"])

    rg = gaps.get("repositoryControlled", {})
    need(rg.get("open") == 0 and rg.get("allClosed") is True and
         all(g.get("state") == "closed" for g in rg.get("gaps", [])), "repository gap ledger")
    gate_rows = external.get("gates")
    need(external.get("repositoryHandoffComplete") is True and isinstance(gate_rows, list) and
         [g.get("id") for g in gate_rows] == EXTERNAL_GATES, "external handoff")
    for gate in gate_rows:
        need(gate.get("state") == "open" and gate.get("selfCertifiable") is False and
             gate.get("requiredEvidence"), f"external gate {gate.get('id')}")

    need([m.get("module") for m in modules] == MODULES, "module map order")
    mapped = delegated = 0
    referenced_tests: set[str] = set()
    operation_ids: set[str] = set()
    for expected_path, module_map in zip(index["moduleMapPaths"], modules):
        module = module_map["module"]
        need(expected_path == f"docs/modules/{module}/IMPLEMENTATION_MAP.json", f"{module} map path")
        need(module_map.get("schema") == "hepta.lane-b-module-implementation-map.v1", f"{module} schema")
        same_subject(module_map.get("sourceSubject"), subject, module)
        roots, integration = module_map.get("canonicalRoots"), module_map.get("integrationRoots")
        need(isinstance(roots, list) and roots and isinstance(integration, list), f"{module} roots")
        ops = module_map.get("operations")
        need(isinstance(ops, list) and [o.get("designOperation") for o in ops] == EXPECTED_OPERATIONS[module],
             f"{module} operations")
        need(module_map.get("repositoryControlledGaps") == [] and module_map.get("externalEvidenceGaps"),
             f"{module} gap disposition")
        need(set(module_map.get("externalGateIds", [])) <= set(EXTERNAL_GATES), f"{module} gates")
        for op in ops:
            name = op["designOperation"]
            full = f"{module}/{name}"
            operation_ids.add(full)
            need(op.get("mappingState") == "closed" and
                 op.get("repositoryImplementationState") == "implemented", f"{full} state")
            op_tests = op.get("testIds")
            need(op_tests and set(op_tests) <= tests_by_module[module], f"{full} tests")
            referenced_tests.update(op_tests)
            if inspect_source:
                verify_anchor(module, name, op.get("ownerEntrypoint"), roots, "owner")
            callee = op.get("delegatedCallee")
            if callee is not None:
                need(integration and callee.get("module") in MODULES, f"{full} delegated owner")
                if inspect_source:
                    verify_anchor(module, name, callee, integration, "callee")
                delegated += 1
            mapped += 1
        if inspect_source:
            for root in roots:
                need((ROOT / root).exists(), f"{module} missing root {root}")
            verify_document(ROOT / f"docs/modules/{module}/TECHNICAL.md",
                            f"# {module} technical development guide", TECHNICAL_HEADINGS, module)
            verify_document(ROOT / f"qualification/module-execution-dossiers/detail/{module}.md",
                            f"# {module}: implementation design", DOSSIER_HEADINGS, module)
    need(mapped == 39 and referenced_tests == set(ids), "operation/test closure")
    need(case_operations == operation_ids, "acceptance cases do not cover the exact operation set")
    return mapped, delegated


def verify_companions(bundle: dict[str, Any]) -> int:
    digest, subject = truth_digest(), bundle["index"]["sourceSubject"]
    for relative in GENERATED_DOCS:
        path = ROOT / relative
        need(path.is_file(), f"missing companion {relative}")
        text = path.read_text(encoding="utf-8")
        need(subject["baseCommit"] in text and subject["baseTree"] in text and digest in text,
             f"stale companion {relative}")
        need(not FORBIDDEN.search(text), f"unresolved marker {relative}")
    native = load_json(ROOT / "qualification/lane-b/NATIVE_BINDINGS.json")
    need(native.get("truthIndexSha256") == digest and native.get("operationCount") == 39 and
         len(native.get("bindings", [])) == 39 and native.get("allOperationMappingsClosed") is True,
         "native bindings")
    closure = (ROOT / "qualification/lane-b/LANE_B_NATIVE_CLOSURE.md").read_text(encoding="utf-8")
    for module in MODULES:
        need(f"`{module}`" in closure, f"native closure missing {module}")
    composition = ROOT / bundle["index"]["validatedArchitectureDocument"]
    need(composition.is_file(), "composition missing")
    text = composition.read_text(encoding="utf-8")
    need(text.startswith("# Lane B runtime composition and failure semantics\n"), "composition title")
    positions = [text.find(h) for h in COMPOSITION_HEADINGS]
    need(all(p >= 0 for p in positions) and positions == sorted(positions), "composition sections")
    need(subject["baseCommit"] in text and subject["baseTree"] in text and digest in text,
         "composition source")
    for module in MODULES:
        need(module in text, f"composition missing {module}")
    return len(GENERATED_DOCS)


def verify_git(manifest: dict[str, Any]) -> tuple[str, list[str]]:
    head, base = run_git("rev-parse", "HEAD"), manifest["baseCommit"]
    expected = os.environ.get("EXPECTED_SHA")
    if expected:
        need(head == expected, "HEAD differs from EXPECTED_SHA")
    need(run_git("rev-parse", f"{base}^{{tree}}") == manifest["baseTree"], "base tree")
    explicit = os.environ.get("HEPTA_LANE_B_VERIFY_MODE")
    mode = explicit or ("merge" if len(run_git("rev-list", "--parents", "-n", "1", "HEAD").split()) == 3 else "source")
    need(mode in {"source", "merge"}, "verify mode")
    if mode == "source":
        need(run_git("rev-parse", "HEAD^") == base and run_git("rev-list", "--count", f"{base}..HEAD") == "1",
             "source must be one direct child")
        need(not run_git("rev-list", "--merges", f"{base}..HEAD"), "source merge commit")
        source = head
    else:
        parents = run_git("rev-list", "--parents", "-n", "1", "HEAD").split()
        need(len(parents) == 3 and parents[1] == base, "synthetic merge parents")
        source = parents[2]
        need(source == os.environ.get("EXPECTED_SOURCE_SHA", source), "merge source")
        need(base == os.environ.get("EXPECTED_BASE_SHA", base), "merge base")
        need(run_git("rev-parse", f"{source}^") == base, "source parent under merge")
        need(run_git("rev-parse", "HEAD^{tree}") == run_git("rev-parse", f"{source}^{{tree}}"),
             "synthetic merge tree")
    changed = [p for p in run_git("diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base}..{source}").splitlines() if p]
    need(changed, "candidate has no changes")
    denied = [p for p in changed if not path_allowed(p, manifest["allowedPathPrefixes"])]
    need(not denied, "path outside envelope: " + ", ".join(denied))
    for path in changed:
        if path.startswith(".github/workflows/hepta-lane-b-"):
            text = (ROOT / path).read_text(encoding="utf-8").lower()
            need("contents: write" not in text and "pull-requests: write" not in text and
                 "git push" not in text and "persist-credentials: false" in text, f"unsafe workflow {path}")
    return mode, changed


def verify_repository() -> dict[str, Any]:
    bundle = load_bundle()
    mapped, delegated = verify_structure(bundle, inspect_source=True)
    companions = verify_companions(bundle)
    mode, changed = verify_git(bundle["manifest"])
    result = {
        "status": "PASS_HEPTA_LANE_B_V3", "mode": mode, "modules": 11,
        "operationsMapped": mapped, "delegatedOperations": delegated,
        "acceptanceTestsTraced": 44, "companions": companions,
        "changedPaths": len(changed), "repositoryControlledGapsOpen": 0,
        "externalGatesOpen": 9, "productExecutionProved": False,
        "deploymentProved": False, "independentAcceptanceProved": False,
    }
    print(json.dumps(result, sort_keys=True))
    return result


def self_test() -> dict[str, Any]:
    need(pairs([("a", 1), ("b", 2)]) == {"a": 1, "b": 2}, "pairs")
    try:
        pairs([("a", 1), ("a", 2)])
    except Invalid:
        pass
    else:
        raise Invalid("duplicate key self-test")
    need(path_allowed("qualification/lane-b/a", ["qualification/lane-b/"]), "path allow")
    need(not path_allowed("docs/DEVELOPMENT.md", ["qualification/lane-b/"]), "path deny")
    need(symbol_occurrences(" pub fn run() {}\nrun();\n", "pub fn run(") == 1, "symbol")
    need(len(MODULES) == 11 and sum(map(len, EXPECTED_OPERATIONS.values())) == 39, "closed sets")
    result = {"status": "PASS_HEPTA_LANE_B_V3_SELF_TEST", "modules": 11, "operations": 39, "externalGates": 9}
    print(json.dumps(result, sort_keys=True))
    return result
