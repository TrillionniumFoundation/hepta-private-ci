#!/usr/bin/env python3
"""Fail-closed verifier for the exact Lane B source candidate."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "qualification/lane-b/LANE_B_CANDIDATE_MANIFEST.json"
TRUTH_PATH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"

MODULES = [
    "runtime.supervisor",
    "runtime.fleet",
    "runtime.agentd",
    "runtime.codex",
    "inference.control",
    "inference.worker",
    "automation.taskflow",
    "channel.matrix",
    "browser.servo",
    "ui.control",
    "ui.native",
]
EXPECTED_OPERATIONS = {
    "runtime.supervisor": ["start_instance", "observe_health", "drain", "load_next"],
    "runtime.fleet": ["admit_host", "allocate", "renew_or_revoke"],
    "runtime.agentd": ["compose_runtime", "start_run", "cancel_run", "attach_context"],
    "runtime.codex": [
        "open_thread",
        "submit_turn",
        "dispatch_tool",
        "observe_delivery",
    ],
    "inference.control": ["reserve_request", "schedule", "cancel", "settle"],
    "inference.worker": ["load_model", "run", "unload"],
    "automation.taskflow": [
        "register_schedule",
        "materialize_due",
        "claim_occurrence",
        "execute_step",
    ],
    "channel.matrix": ["admit_event", "prepare_send", "observe_send"],
    "browser.servo": ["open_profile", "observe_page", "navigate_or_act"],
    "ui.control": ["read_view", "submit_request", "request_stop"],
    "ui.native": [
        "connect_runtime",
        "render_runtime_view",
        "request_platform_capability",
        "apply_shell_update",
    ],
}
ALLOWED_STATES = {"implemented", "implemented_partial", "boundary_only", "planned"}
TECHNICAL_HEADINGS = [
    "## 1. Identity, mission and ownership",
    "## 2. Source binding and implementation status",
    "## 3. Boundary, responsibilities and non-goals",
    "## 5. Contracts, ports and compatibility",
    "## 6. Data authority, persistence and migrations",
    "## 7. Runtime, concurrency and transaction model",
    "## 8. Failure semantics, recovery and rollback",
    "## 9. Security, privacy and threat controls",
    "## 10. Performance, capacity and hot-path policy",
    "## 11. Observability and operations",
    "## 12. Verification and qualification",
    "## 13. Implementation sequence and work packages",
    "## 14. Activation, compatibility and retirement",
    "## 15. Definition of module completion",
    "## 16. V8.2 pre-coding implementation-readiness overlay",
]
DOSSIER_HEADINGS = [
    "## 1. Source and work envelope",
    "## 2. Public operations and contract details",
    "## 3. State records and transaction design",
    "## 4. Deterministic algorithm and scheduling",
    "## 5. Capacity and performance profile",
    "## 6. Concrete verification cases",
    "## 7. Integration, rollback and capability ceiling",
]
FORBIDDEN_MARKER = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE)


class Invalid(ValueError):
    """Candidate or truth input violates a fail-closed invariant."""


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise Invalid(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:  # pragma: no cover - diagnostic wrapper
        raise Invalid(f"{path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise Invalid(f"{path.relative_to(ROOT)}: root must be an object")
    return value


def run_git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise Invalid(f"git {' '.join(args)} failed: {detail}")
    return process.stdout.strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def path_allowed(path: str, prefixes: list[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def verify_candidate(manifest: dict[str, Any]) -> list[str]:
    require(
        manifest.get("schema") == "hepta.lane-b-candidate-manifest.v2"
        and manifest.get("schemaVersion") == 2,
        "candidate manifest schema",
    )
    require(
        manifest.get("repository") == "TrillionniumFoundation/hepta-private-ci",
        "candidate repository identity",
    )
    require(manifest.get("requiredModuleGuides") == MODULES, "candidate module order")
    base = manifest.get("baseCommit")
    tree = manifest.get("baseTree")
    require(
        isinstance(base, str) and re.fullmatch(r"[0-9a-f]{40}", base) is not None,
        "base commit",
    )
    require(
        isinstance(tree, str) and re.fullmatch(r"[0-9a-f]{40}", tree) is not None,
        "base tree",
    )
    require(run_git("rev-parse", f"{base}^{{tree}}") == tree, "base tree mismatch")
    require(run_git("rev-parse", "HEAD^") == base, "candidate must be one direct child")
    require(
        run_git("rev-list", "--count", f"{base}..HEAD") == "1",
        "candidate must contain exactly one commit",
    )
    require(
        not run_git("rev-list", "--merges", f"{base}..HEAD"),
        "merge commit in candidate",
    )

    prefixes = manifest.get("allowedPathPrefixes")
    require(
        isinstance(prefixes, list)
        and prefixes
        and all(isinstance(prefix, str) and prefix for prefix in prefixes),
        "allowed path prefixes",
    )
    changed = [
        line
        for line in run_git(
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            f"{base}..HEAD",
        ).splitlines()
        if line
    ]
    require(changed, "candidate has no changes")
    denied = [path for path in changed if not path_allowed(path, prefixes)]
    require(
        not denied,
        "candidate changed path outside envelope: " + ", ".join(denied),
    )
    for path in changed:
        if path.startswith(".github/workflows/hepta-lane-b-"):
            text = (ROOT / path).read_text(encoding="utf-8").lower()
            require("contents: write" not in text, f"{path}: write permission")
            require("pull-requests: write" not in text, f"{path}: PR write permission")
            require("git push" not in text, f"{path}: source mutation")
            require(
                "persist-credentials: false" in text,
                f"{path}: checkout credentials must not persist",
            )
    return changed


def verify_document(path: Path, title: str, headings: list[str], module: str) -> None:
    require(path.is_file(), f"missing {path.relative_to(ROOT)}")
    text = path.read_text(encoding="utf-8")
    require(text.startswith(title + "\n"), f"{path.relative_to(ROOT)} title")
    require(
        not FORBIDDEN_MARKER.search(text),
        f"{path.relative_to(ROOT)} unresolved marker",
    )
    positions = [text.find(heading) for heading in headings]
    require(
        all(position >= 0 for position in positions),
        f"{path.relative_to(ROOT)} section",
    )
    require(positions == sorted(positions), f"{path.relative_to(ROOT)} section order")
    require(module in text, f"{path.relative_to(ROOT)} module identity")
    for phrase in ("rollback", "authority", "verification"):
        require(phrase in text.lower(), f"{path.relative_to(ROOT)} missing {phrase}")


def symbol_occurrences(text: str, symbol: str) -> int:
    """Count declaration-shaped source anchors, not arbitrary call-site substrings."""
    count = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith(symbol):
            continue
        if len(stripped) > len(symbol) and (symbol[-1].isalnum() or symbol[-1] == "_"):
            following = stripped[len(symbol)]
            if following.isalnum() or following == "_":
                continue
        count += 1
    return count


def verify_operation(module: str, roots: list[str], operation: dict[str, Any]) -> bool:
    required = {
        "designOperation",
        "state",
        "path",
        "symbol",
        "callerClass",
        "buildTarget",
    }
    require(set(operation) == required, f"{module}: operation field set")
    state = operation.get("state")
    require(state in ALLOWED_STATES, f"{module}: unknown operation state {state}")
    require(
        isinstance(operation.get("callerClass"), str) and operation["callerClass"],
        f"{module}: caller class",
    )
    if state == "planned":
        require(
            operation.get("path") is None
            and operation.get("symbol") is None
            and operation.get("buildTarget") is None,
            f"{module}/{operation.get('designOperation')}: planned operation invented source",
        )
        return False

    path = operation.get("path")
    symbol = operation.get("symbol")
    target = operation.get("buildTarget")
    require(isinstance(path, str) and path, f"{module}: mapped path")
    require(isinstance(symbol, str) and len(symbol) >= 6, f"{module}: mapped symbol")
    require(isinstance(target, str) and target, f"{module}: build target")
    require(
        any(path == root or path.startswith(root + "/") for root in roots),
        f"{module}: owner-root escape",
    )
    source = ROOT / path
    require(source.is_file(), f"{module}: missing mapped source {path}")
    text = source.read_text(encoding="utf-8")
    occurrences = symbol_occurrences(text, symbol)
    require(occurrences > 0, f"{module}: missing mapped symbol {symbol!r} in {path}")
    require(
        occurrences == 1,
        f"{module}: mapped symbol {symbol!r} is not unique in {path}",
    )
    require(
        not path.endswith("_tests.rs") and "/tests/" not in path,
        f"{module}: test-only mapping",
    )
    return True


def verify_truth(truth: dict[str, Any], manifest: dict[str, Any]) -> tuple[int, int]:
    require(
        truth.get("schema") == "hepta.lane-b-implementation-truth.v2"
        and truth.get("schemaVersion") == 2,
        "truth schema",
    )
    require(truth.get("planId") == manifest.get("planId"), "truth plan identity")
    require(
        truth.get("planVersion") == manifest.get("planVersion"), "truth plan version"
    )
    require(truth.get("laneId") == "LANE-B-RUNTIME", "truth lane")
    require(
        truth.get("baseline", {}).get("commit") == manifest.get("baseCommit"),
        "truth base",
    )
    require(
        truth.get("baseline", {}).get("tree") == manifest.get("baseTree"),
        "truth tree",
    )
    claims = truth.get("claimBoundary")
    require(isinstance(claims, dict), "claim boundary")
    for key in (
        "repositoryTruthModelClosed",
        "laneModuleSetClosed",
        "observedSourceAnchorsClosed",
        "currentMappingDebtClosed",
    ):
        require(claims.get(key) is True, f"truth positive repository claim {key}")
    for key in (
        "targetDesignImplementationClosed",
        "productionConsumerCallsitesProved",
        "productExecutionProved",
        "deploymentProved",
        "independentAcceptanceProved",
        "externalEffectsProved",
        "hardwareEvidenceProved",
        "futureWindowEfficacyProved",
    ):
        require(claims.get(key) is False, f"unsupported positive claim {key}")
    require(truth.get("moduleOrder") == MODULES, "truth module order")
    rows = truth.get("modules")
    require(isinstance(rows, list), "truth modules")
    require(
        [row.get("module") for row in rows] == MODULES,
        "truth module closed world",
    )

    mapped = 0
    planned = 0
    for row in rows:
        module = row["module"]
        roots = row.get("declaredRoots")
        require(isinstance(roots, list) and roots, f"{module}: declared roots")
        for root in roots:
            require((ROOT / root).exists(), f"{module}: missing declared root {root}")
        operations = row.get("operations")
        require(isinstance(operations, list), f"{module}: operations")
        require(
            [operation.get("designOperation") for operation in operations]
            == EXPECTED_OPERATIONS[module],
            f"{module}: operation coverage/order",
        )
        for operation in operations:
            if verify_operation(module, roots, operation):
                mapped += 1
            else:
                planned += 1
        require(
            row.get("productionCallerState") == "unproved",
            f"{module}: product caller claim",
        )
        require(
            row.get("productExecutionState") == "unproved",
            f"{module}: product execution claim",
        )
        for key in ("stateDisposition", "terminalObserverDisposition"):
            require(
                isinstance(row.get(key), str) and len(row[key]) >= 40,
                f"{module}: {key}",
            )
        gaps = row.get("residualGaps")
        require(
            isinstance(gaps, list)
            and gaps
            and all(isinstance(gap, str) and len(gap) >= 20 for gap in gaps),
            f"{module}: residual gaps",
        )
        verify_document(
            ROOT / f"docs/modules/{module}/TECHNICAL.md",
            f"# {module} technical development guide",
            TECHNICAL_HEADINGS,
            module,
        )
        verify_document(
            ROOT / f"qualification/module-execution-dossiers/detail/{module}.md",
            f"# {module}: implementation design",
            DOSSIER_HEADINGS,
            module,
        )
    require(mapped + planned == 39, "Lane B operation count")
    require(planned == 0, "currentMappingDebtClosed requires plannedOperations=0")
    require(mapped == 39, "currentMappingDebtClosed requires mappedOperations=39")
    return mapped, planned


def verify() -> int:
    manifest = load_json(MANIFEST_PATH)
    truth = load_json(TRUTH_PATH)
    changed = verify_candidate(manifest)
    mapped, planned = verify_truth(truth, manifest)
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_EXACT_CANDIDATE",
                "changedPaths": len(changed),
                "modules": len(MODULES),
                "operations": mapped + planned,
                "mappedOperations": mapped,
                "plannedOperations": planned,
                "repositoryTruthModelClosed": True,
                "targetDesignImplementationClosed": False,
                "productExecutionProved": False,
                "independentAcceptanceProved": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    require(pairs([("a", 1), ("b", 2)]) == {"a": 1, "b": 2}, "pairs")
    try:
        pairs([("a", 1), ("a", 2)])
    except Invalid:
        pass
    else:  # pragma: no cover
        raise Invalid("duplicate key self-test")
    require(
        path_allowed("qualification/lane-b/a.json", ["qualification/lane-b/"]),
        "path allow",
    )
    require(
        not path_allowed("docs/DEVELOPMENT.md", ["qualification/lane-b/"]),
        "path deny",
    )
    require(
        symbol_occurrences("pub struct A {}\npub struct AB {}\n", "pub struct A") == 1,
        "symbol identifier boundary",
    )
    require(
        symbol_occurrences("  readView() {\nthis.readView();\n", "readView()") == 1,
        "symbol declaration shape",
    )
    require(
        len(MODULES) == 11 and sum(map(len, EXPECTED_OPERATIONS.values())) == 39,
        "closed sets",
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_CANDIDATE_SELF_TEST",
                "modules": 11,
                "operations": 39,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "self-test"])
    args = parser.parse_args()
    try:
        return verify() if args.command == "verify" else self_test()
    except (Invalid, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_EXACT_CANDIDATE: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
