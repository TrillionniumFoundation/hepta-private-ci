#!/usr/bin/env python3
"""Single fail-closed verifier/generator for Lane B source truth."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRUTH_PATH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"
MANIFEST_PATH = ROOT / "qualification/lane-b/LANE_B_CANDIDATE_MANIFEST.json"
TRACE_PATH = ROOT / "qualification/lane-b/TEST_TRACEABILITY.json"
NATIVE_PATH = ROOT / "qualification/lane-b/LANE_B_NATIVE_CLOSURE.md"
COMPOSITION_PATH = ROOT / "docs/readiness/LANE_B_RUNTIME_COMPOSITION.md"
README_PATH = ROOT / "qualification/lane-b/README.md"
EXPECTED_MODULES = [
    "runtime.supervisor", "runtime.fleet", "runtime.agentd", "runtime.codex",
    "inference.control", "inference.worker", "automation.taskflow", "channel.matrix",
    "browser.servo", "ui.control", "ui.native",
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
FORBIDDEN = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.IGNORECASE)
HEX40 = re.compile(r"[0-9a-f]{40}")


class Invalid(ValueError):
    pass


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
    except Exception as exc:
        raise Invalid(f"{path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise Invalid(f"{path.relative_to(ROOT)}: root must be an object")
    return value


def dump_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def need(condition: bool, message: str) -> None:
    if not condition:
        raise Invalid(message)


def git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=ROOT, check=False, capture_output=True, text=True
    )
    if process.returncode != 0:
        raise Invalid(
            f"git {' '.join(args)} failed: "
            f"{process.stderr.strip() or process.stdout.strip()}"
        )
    return process.stdout.strip()


def path_allowed(path: str, prefixes: list[str]) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in prefixes)


def module_map(truth: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    index = truth["moduleOrder"].index(row["module"])
    return {
        "schema": "hepta.module-implementation-map.v1",
        "schemaVersion": 1,
        "sourceBase": truth["sourceBase"],
        "laneId": truth["laneId"],
        "module": row["module"],
        "truthPath": "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json",
        "truthPointer": f"/modules/{index}",
        "sourceMaturity": row["sourceMaturity"],
        "declaredRoots": row["declaredRoots"],
        "resolvedRoots": row["resolvedRoots"],
        "operationIds": [
            operation["designOperation"] for operation in row["operations"]
        ],
        "repositoryControlledGaps": row["repositoryControlledGaps"],
        "externalEvidenceGates": row["externalEvidenceGates"],
        "claimBoundary": {
            "nativeSourceMappingComplete": True,
            "repositoryControlledGapsClosed": True,
            "productExecutionComplete": False,
            "deploymentQualificationComplete": False,
            "independentAcceptanceComplete": False,
        },
    }


def traceability(truth: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for row in truth["modules"]:
        for operation in row["operations"]:
            entries.append(
                {
                    "module": row["module"],
                    "designOperation": operation["designOperation"],
                    "mappingClass": operation["mappingClass"],
                    "ownerEntrypoint": operation["ownerEntrypoint"],
                    "tests": operation["tests"],
                    "workflow": ".github/workflows/hepta-lane-b-truth.yml",
                    "executionEvidence": (
                        "exact_head_and_synthetic_merge_workflow_required"
                    ),
                    "externalEvidenceRequired": bool(row["externalEvidenceGates"]),
                }
            )
    return {
        "schema": "hepta.lane-b-test-traceability.v1",
        "schemaVersion": 1,
        "sourceBase": truth["sourceBase"],
        "laneId": truth["laneId"],
        "moduleCount": len(truth["modules"]),
        "operationCount": len(entries),
        "entries": entries,
        "claimBoundary": {
            "testPathCoverageComplete": True,
            "workflowExecutionRequired": True,
            "productExecutionProvedByRegistry": False,
            "externalEffectsProvedByRegistry": False,
        },
    }


def render_native_closure(truth: dict[str, Any]) -> str:
    base = truth["sourceBase"]
    lines = [
        "# Lane B native source and implementation closure",
        "",
        "**Lane:** `LANE-B-RUNTIME`  ",
        f"**Immutable source base:** `{base['commit']}` / tree `{base['tree']}`  ",
        "**Exact candidate:** derived from `git rev-parse HEAD` by the verifier; never hard-coded into this document  ",
        "**Repository-controlled state:** documentation, operation inventory, source mapping and source-boundary gaps closed  ",
        "**External state:** product execution, deployment, external effects and independent acceptance remain open until externally evidenced",
        "",
        "## 1. Truth model",
        "",
        "This file is generated from `qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json`. The machine truth, eleven module `IMPLEMENTATION_MAP.json` projections, this document and `TEST_TRACEABILITY.json` must be byte-for-byte reproducible from the same source. A native symbol proves a repository source boundary only; it does not prove a deployed caller, real provider/model, Servo network effect, Matrix homeserver terminal observation, signed application package or independent acceptance.",
        "",
        "The previous ambiguous flag `currentMappingDebtClosed` is removed. Closure is split into documentation structure, operation inventory, native source mapping, repository source boundary, product execution, deployment and independent acceptance.",
        "",
    ]
    for index, row in enumerate(truth["modules"], start=2):
        lines.extend(
            [
                f"## {index}. `{row['module']}`",
                "",
                f"**Source maturity:** `{row['sourceMaturity']}`  ",
                "**Declared roots:** "
                + ", ".join(f"`{root}`" for root in row["declaredRoots"])
                + "  ",
                "**Resolved roots:** "
                + ", ".join(f"`{root}`" for root in row["resolvedRoots"]),
                "",
                row["stateOwnerDisposition"],
                "",
                row["terminalObserverDisposition"],
                "",
                "| Design operation | Mapping | Owner entrypoint | Build target | Tests |",
                "|---|---|---|---|---|",
            ]
        )
        for operation in row["operations"]:
            owner = operation["ownerEntrypoint"]
            tests = ", ".join(f"`{case['path']}`" for case in operation["tests"])
            lines.append(
                f"| `{operation['designOperation']}` | `{operation['mappingClass']}` | "
                f"`{owner['path']}` — `{owner['symbol']}` | "
                f"`{owner['buildTarget']}` | {tests} |"
            )
        lines.extend(
            [
                "",
                "**Repository-controlled gaps:** none in the declared documentation/mapping/source-boundary scope.",
                "",
                "**External evidence still required:**",
                "",
            ]
        )
        lines.extend(f"- {gap}" for gap in row["externalEvidenceGates"])
        lines.extend(["", "**Source semantics:**", ""])
        lines.extend(
            f"- `{operation['designOperation']}` — {operation['sourceSemantics']}"
            for operation in row["operations"]
        )
        lines.append("")
    lines.extend(
        [
            "## 13. Cross-module acceptance boundary",
            "",
            "At one exact head and deterministic synthetic merge, repository-controlled closure requires all 39 operations to have an owner entrypoint, build target, source symbol and test path; every owner entrypoint to remain inside its declared or explicitly resolved owner roots; Agentd delegation to name the downstream owner rather than substituting a downstream symbol for the Agentd entrypoint; all eleven module maps and the test traceability registry to equal the central truth projection; and the exact-head and synthetic-merge workflow to execute successfully.",
            "",
            "This state does not close deployment or external gates. Real provider/model execution, real Servo and Matrix effects, deployed Web/native artifacts, target-host measurements, hardware evidence, external-owner consent, independent review, selection, promotion and release remain separately governed. The verifier rejects any attempt to turn these open gates into repository-authored positive evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def verify_candidate(manifest: dict[str, Any], truth: dict[str, Any]) -> list[str]:
    need(
        manifest.get("schema") == "hepta.lane-b-candidate-manifest.v3",
        "candidate schema",
    )
    need(
        manifest.get("sourceBase") == truth.get("sourceBase"),
        "manifest/truth source base",
    )
    base = manifest["sourceBase"]["commit"]
    tree = manifest["sourceBase"]["tree"]
    need(
        bool(HEX40.fullmatch(base)) and bool(HEX40.fullmatch(tree)),
        "source base shape",
    )
    need(git("rev-parse", f"{base}^{{tree}}") == tree, "source base tree mismatch")
    need(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", base, "HEAD"],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0,
        "source base is not ancestor of HEAD",
    )
    synthetic = os.environ.get("HEPTA_SYNTHETIC_MERGE") == "1"
    parents = git("show", "-s", "--format=%P", "HEAD").split()
    if synthetic:
        need(len(parents) == 2, "synthetic merge must have exactly two parents")
    else:
        need(
            not git("rev-list", "--merges", f"{base}..HEAD"),
            "source-head candidate contains merge commits",
        )
    prefixes = manifest.get("allowedPathPrefixes")
    need(isinstance(prefixes, list) and prefixes, "allowed path prefixes")
    changed = [
        line
        for line in git(
            "diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base}..HEAD"
        ).splitlines()
        if line
    ]
    need(changed, "candidate has no changes")
    denied = [path for path in changed if not path_allowed(path, prefixes)]
    need(not denied, "candidate path outside envelope: " + ", ".join(denied))
    return changed


def verify_anchor(
    module: str, roots: list[str], value: dict[str, Any], owner: bool
) -> None:
    need(
        set(value) >= {"role", "path", "symbol", "buildTarget"},
        f"{module}: anchor fields",
    )
    path = value["path"]
    need(isinstance(path, str) and path, f"{module}: anchor path")
    if owner:
        need(
            any(path == root or path.startswith(root + "/") for root in roots),
            f"{module}: owner entrypoint escapes resolved roots: {path}",
        )
    else:
        need(
            isinstance(value.get("ownerModule"), str) and value["ownerModule"],
            f"{module}: delegated anchor missing owner module",
        )
    source = ROOT / path
    need(source.is_file(), f"{module}: missing source {path}")
    text = source.read_text(encoding="utf-8")
    need(
        value["symbol"] in text,
        f"{module}: missing symbol {value['symbol']!r} in {path}",
    )
    need(
        isinstance(value["buildTarget"], str) and value["buildTarget"],
        f"{module}: build target",
    )


def verify_truth(truth: dict[str, Any]) -> tuple[int, int]:
    need(
        truth.get("schema") == "hepta.lane-b-implementation-truth.v3"
        and truth.get("schemaVersion") == 3,
        "truth schema",
    )
    need(truth.get("moduleOrder") == EXPECTED_MODULES, "module order")
    need(truth.get("operationCount") == 39, "declared operation count")
    claims = truth.get("claimBoundary", {})
    for key in (
        "documentationStructureComplete",
        "designOperationInventoryComplete",
        "nativeSourceMappingComplete",
        "repositoryControlledDocumentationGapsClosed",
        "repositoryControlledMappingGapsClosed",
        "repositoryControlledSourceBoundaryGapsClosed",
    ):
        need(claims.get(key) is True, f"missing repository closure {key}")
    for key in (
        "targetDesignImplementationComplete",
        "productionConsumerCallsitesComplete",
        "productExecutionComplete",
        "deploymentQualificationComplete",
        "independentAcceptanceComplete",
        "externalEffectsComplete",
        "hardwareEvidenceComplete",
        "futureWindowEfficacyComplete",
        "allGapsClosed",
    ):
        need(claims.get(key) is False, f"unsupported positive claim {key}")
    rows = truth.get("modules")
    need(
        isinstance(rows, list)
        and [row.get("module") for row in rows] == EXPECTED_MODULES,
        "module closed world",
    )
    roots_by_module = {row["module"]: row.get("resolvedRoots", []) for row in rows}
    operations = 0
    tests = 0
    for row in rows:
        module = row["module"]
        need(
            row.get("repositoryControlledGaps") == [],
            f"{module}: repository gaps remain",
        )
        need(
            isinstance(row.get("externalEvidenceGates"), list)
            and row["externalEvidenceGates"],
            f"{module}: external gates missing",
        )
        roots = row.get("resolvedRoots")
        need(isinstance(roots, list) and roots, f"{module}: resolved roots")
        for root in roots:
            need((ROOT / root).exists(), f"{module}: missing root {root}")
        module_ops = row.get("operations")
        need(isinstance(module_ops, list), f"{module}: operations")
        need(
            [item.get("designOperation") for item in module_ops]
            == EXPECTED_OPERATIONS[module],
            f"{module}: operation coverage/order",
        )
        for item in module_ops:
            operations += 1
            need(
                item.get("mappingClass") in truth["allowedMappingClasses"],
                f"{module}: mapping class",
            )
            verify_anchor(module, roots, item["ownerEntrypoint"], True)
            for delegate in item.get("delegatedCallees", []):
                verify_anchor(module, roots, delegate, False)
                delegate_owner = delegate["ownerModule"]
                need(
                    delegate_owner in roots_by_module,
                    f"{module}: unknown delegated owner {delegate_owner}",
                )
                delegate_path = delegate["path"]
                need(
                    any(
                        delegate_path == root
                        or delegate_path.startswith(root + "/")
                        for root in roots_by_module[delegate_owner]
                    ),
                    f"{module}: delegated path escapes {delegate_owner} roots: {delegate_path}",
                )
            cases = item.get("tests")
            need(
                isinstance(cases, list) and cases,
                f"{module}/{item['designOperation']}: tests",
            )
            for case in cases:
                tests += 1
                path = ROOT / case["path"]
                need(
                    path.is_file(),
                    f"{module}/{item['designOperation']}: missing test {case['path']}",
                )
                need(
                    isinstance(case.get("command"), str) and case["command"],
                    f"{module}: test command",
                )
            need(
                isinstance(item.get("sourceSemantics"), str)
                and len(item["sourceSemantics"]) >= 40,
                f"{module}: source semantics",
            )
        guide = ROOT / f"docs/modules/{module}/TECHNICAL.md"
        design = ROOT / f"qualification/module-execution-dossiers/detail/{module}.md"
        for path in (guide, design):
            need(path.is_file(), f"{module}: missing {path.relative_to(ROOT)}")
            text = path.read_text(encoding="utf-8")
            need(
                module in text and not FORBIDDEN.search(text),
                f"{module}: invalid technical document {path.relative_to(ROOT)}",
            )
    need(operations == 39, "operation closed world")
    return operations, tests


def generated_files(truth: dict[str, Any]) -> dict[Path, str]:
    files: dict[Path, str] = {
        TRACE_PATH: dump_json(traceability(truth)),
        NATIVE_PATH: render_native_closure(truth),
    }
    for row in truth["modules"]:
        files[ROOT / f"docs/modules/{row['module']}/IMPLEMENTATION_MAP.json"] = (
            dump_json(module_map(truth, row))
        )
    return files


def verify_generated(truth: dict[str, Any]) -> None:
    for path, expected in generated_files(truth).items():
        need(path.is_file(), f"missing generated file {path.relative_to(ROOT)}")
        actual = path.read_text(encoding="utf-8")
        need(
            actual == expected,
            f"generated projection drift: {path.relative_to(ROOT)}",
        )
    composition = COMPOSITION_PATH.read_text(encoding="utf-8")
    base = truth["sourceBase"]
    need(
        base["commit"] in composition and base["tree"] in composition,
        "composition source base drift",
    )
    need(
        "product execution" in composition.lower()
        and "independent acceptance" in composition.lower(),
        "composition claim boundary",
    )
    readme = README_PATH.read_text(encoding="utf-8")
    need(
        "hepta-lane-b-truth.py verify" in readme and not FORBIDDEN.search(readme),
        "Lane B README",
    )


def generate(truth: dict[str, Any]) -> int:
    for path, content in generated_files(truth).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "GENERATED_HEPTA_LANE_B_PROJECTIONS",
                "files": len(generated_files(truth)),
            },
            sort_keys=True,
        )
    )
    return 0


def verify() -> int:
    truth = load_json(TRUTH_PATH)
    manifest = load_json(MANIFEST_PATH)
    changed = verify_candidate(manifest, truth)
    operations, tests = verify_truth(truth)
    verify_generated(truth)
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_SOURCE_CLOSURE",
                "exactHead": git("rev-parse", "HEAD"),
                "exactTree": git("rev-parse", "HEAD^{tree}"),
                "changedPaths": len(changed),
                "modules": len(EXPECTED_MODULES),
                "operations": operations,
                "testBindings": tests,
                "repositoryControlledSourceBoundaryGapsClosed": True,
                "productExecutionComplete": False,
                "externalEffectsComplete": False,
                "independentAcceptanceComplete": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    need(pairs([("a", 1), ("b", 2)]) == {"a": 1, "b": 2}, "pairs")
    try:
        pairs([("a", 1), ("a", 2)])
    except Invalid:
        pass
    else:
        raise Invalid("duplicate-key self-test")
    need(
        path_allowed("qualification/lane-b/a.json", ["qualification/lane-b/"]),
        "path allow",
    )
    need(
        not path_allowed("docs/DEVELOPMENT.md", ["qualification/lane-b/"]),
        "path deny",
    )
    need(
        len(EXPECTED_MODULES) == 11
        and sum(map(len, EXPECTED_OPERATIONS.values())) == 39,
        "closed sets",
    )
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_B_SOURCE_CLOSURE_SELF_TEST",
                "modules": 11,
                "operations": 39,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "generate", "self-test"])
    args = parser.parse_args()
    truth = load_json(TRUTH_PATH) if args.command == "generate" else None
    if args.command == "generate":
        return generate(truth)
    if args.command == "self-test":
        return self_test()
    return verify()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Invalid as exc:
        raise SystemExit(f"FAIL_HEPTA_LANE_B_SOURCE_CLOSURE: {exc}") from exc
