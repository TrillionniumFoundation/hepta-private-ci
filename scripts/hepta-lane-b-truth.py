#!/usr/bin/env python3
"""Single fail-closed Lane B source-truth verifier and projection generator."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRUTH = ROOT / "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json"
MANIFEST = ROOT / "qualification/lane-b/LANE_B_CANDIDATE_MANIFEST.json"
TRACE = ROOT / "qualification/lane-b/TEST_TRACEABILITY.json"
NATIVE = ROOT / "qualification/lane-b/LANE_B_NATIVE_CLOSURE.md"
COMPOSITION = ROOT / "docs/readiness/LANE_B_RUNTIME_COMPOSITION.md"
README = ROOT / "qualification/lane-b/README.md"
MODULES = [
    "runtime.supervisor", "runtime.fleet", "runtime.agentd", "runtime.codex",
    "inference.control", "inference.worker", "automation.taskflow", "channel.matrix",
    "browser.servo", "ui.control", "ui.native",
]
OPS = {
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
FORBIDDEN = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b", re.I)
HEX40 = re.compile(r"[0-9a-f]{40}")


class Invalid(ValueError):
    pass


def need(ok: bool, message: str) -> None:
    if not ok:
        raise Invalid(message)


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        need(key not in out, f"duplicate JSON key: {key}")
        out[key] = value
    return out


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except Exception as exc:
        raise Invalid(f"{path.relative_to(ROOT)}: {exc}") from exc
    need(isinstance(value, dict), f"{path.relative_to(ROOT)} must be an object")
    return value


def dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    need(result.returncode == 0, result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def allowed(path: str, prefixes: list[str]) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in prefixes)


def module_maps(truth: dict[str, Any]) -> list[dict[str, Any]]:
    index = truth.get("modules")
    need(isinstance(index, list) and len(index) == len(MODULES), "module index")
    out = []
    for position, entry in enumerate(index):
        module = MODULES[position]
        path = f"docs/modules/{module}/IMPLEMENTATION_MAP.json"
        need(entry.get("module") == module and entry.get("mapPath") == path, f"{module}: index")
        row = load(ROOT / path)
        need(row.get("module") == module, f"{module}: map identity")
        need(row.get("sourceBase") == truth.get("sourceBase"), f"{module}: source base")
        ids = [item.get("designOperation") for item in row.get("operations", [])]
        need(ids == entry.get("operationIds") == OPS[module], f"{module}: operation index")
        out.append(row)
    return out


def trace_projection(truth: dict[str, Any], maps: list[dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for row in maps:
        for item in row["operations"]:
            entries.append({
                "module": row["module"],
                "operation": item["designOperation"],
                "map": f"docs/modules/{row['module']}/IMPLEMENTATION_MAP.json",
                "tests": [{"path": test["path"], "command": test["command"]} for test in item["tests"]],
            })
    return {
        "schema": "hepta.lane-b-test-traceability.v1", "schemaVersion": 1,
        "sourceBase": truth["sourceBase"], "laneId": truth["laneId"],
        "moduleCount": len(maps), "operationCount": len(entries), "entries": entries,
        "claimBoundary": {
            "testPathCoverageComplete": True, "workflowExecutionRequired": True,
            "productExecutionProvedByRegistry": False, "externalEffectsProvedByRegistry": False,
        },
    }


def native_projection(truth: dict[str, Any], maps: list[dict[str, Any]]) -> str:
    base = truth["sourceBase"]
    lines = [
        "# Lane B native source and implementation closure", "",
        "**Lane:** `LANE-B-RUNTIME`  ",
        f"**Immutable source base:** `{base['commit']}` / tree `{base['tree']}`  ",
        "**Exact candidate:** derived from Git at verification time; never hard-coded  ",
        "**Repository-controlled scope:** documentation, operation inventory, source mapping and bounded source gaps closed  ",
        "**External scope:** product execution, deployment, real effects and independent acceptance remain open", "",
        "## 1. Truth model", "",
        "The central truth is a closed index. Detailed module roots, ownership, terminal observers, native symbols, delegated callees, tests and external evidence gates live in each module's `IMPLEMENTATION_MAP.json`. This file and `TEST_TRACEABILITY.json` are generated from those maps. A source symbol or fixture is not deployment or external-effect evidence.", "",
    ]
    for number, row in enumerate(maps, start=2):
        lines += [f"## {number}. `{row['module']}`", "", row["stateOwnerDisposition"], "", row["terminalObserverDisposition"], "", "| Operation | Class | Owner entrypoint |", "|---|---|---|"]
        for item in row["operations"]:
            owner = item["ownerEntrypoint"]
            lines.append(f"| `{item['designOperation']}` | `{item['mappingClass']}` | `{owner['path']}` — `{owner['symbol']}` |")
        lines += ["", "External evidence gates:", ""] + [f"- {gate}" for gate in row["externalEvidenceGates"]] + [""]
    lines += [
        "## 13. Cross-module acceptance boundary", "",
        "All 39 operations require an owner entrypoint, build target and test path. Owner entrypoints remain inside owner roots; delegated callees name their real owner. Exact-head and deterministic synthetic-merge validation must agree with all eleven maps and generated projections.", "",
        "Repository source closure does not self-issue real model/provider execution, Servo or Matrix effects, deployed Web/native artifacts, target-host measurements, hardware evidence, external-owner consent, independent acceptance, selection, promotion or release.", "",
    ]
    return "\n".join(lines)


def verify_candidate(manifest: dict[str, Any], truth: dict[str, Any]) -> list[str]:
    need(manifest.get("schema") == "hepta.lane-b-candidate-manifest.v3", "manifest schema")
    need(manifest.get("sourceBase") == truth.get("sourceBase"), "manifest source base")
    base, tree = manifest["sourceBase"]["commit"], manifest["sourceBase"]["tree"]
    need(bool(HEX40.fullmatch(base)) and bool(HEX40.fullmatch(tree)), "base identity")
    need(git("rev-parse", f"{base}^{{tree}}") == tree, "base tree")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=ROOT)
    need(ancestor.returncode == 0, "base is not ancestor")
    if os.environ.get("HEPTA_SYNTHETIC_MERGE") == "1":
        need(len(git("show", "-s", "--format=%P", "HEAD").split()) == 2, "synthetic parents")
    else:
        need(not git("rev-list", "--merges", f"{base}..HEAD"), "merge commit in source candidate")
    prefixes = manifest.get("allowedPathPrefixes")
    need(isinstance(prefixes, list) and prefixes, "path envelope")
    changed = [path for path in git("diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base}..HEAD").splitlines() if path]
    need(changed, "empty candidate")
    denied = [path for path in changed if not allowed(path, prefixes)]
    need(not denied, "path outside envelope: " + ", ".join(denied))
    return changed


def verify_anchor(module: str, roots: list[str], anchor: dict[str, Any], owner: bool) -> None:
    need(set(anchor) >= {"role", "path", "symbol", "buildTarget"}, f"{module}: anchor")
    path = anchor["path"]
    if owner:
        need(any(path == root or path.startswith(root + "/") for root in roots), f"{module}: owner-root escape {path}")
    else:
        need(isinstance(anchor.get("ownerModule"), str), f"{module}: delegated owner")
    source = ROOT / path
    need(source.is_file(), f"{module}: missing source {path}")
    need(anchor["symbol"] in source.read_text(encoding="utf-8"), f"{module}: missing symbol {anchor['symbol']!r}")
    need(isinstance(anchor["buildTarget"], str) and anchor["buildTarget"], f"{module}: build target")


def verify_truth(truth: dict[str, Any], maps: list[dict[str, Any]]) -> tuple[int, int]:
    need(truth.get("schema") == "hepta.lane-b-implementation-truth.v3" and truth.get("schemaVersion") == 3, "truth schema")
    need(truth.get("moduleOrder") == MODULES and truth.get("operationCount") == 39, "truth closed world")
    claims = truth.get("claimBoundary", {})
    positive = ("documentationStructureComplete", "designOperationInventoryComplete", "nativeSourceMappingComplete", "repositoryControlledDocumentationGapsClosed", "repositoryControlledMappingGapsClosed", "repositoryControlledSourceBoundaryGapsClosed")
    negative = ("targetDesignImplementationComplete", "productionConsumerCallsitesComplete", "productExecutionComplete", "deploymentQualificationComplete", "independentAcceptanceComplete", "externalEffectsComplete", "hardwareEvidenceComplete", "futureWindowEfficacyComplete", "allGapsClosed")
    for key in positive: need(claims.get(key) is True, f"missing closure {key}")
    for key in negative: need(claims.get(key) is False, f"unsupported claim {key}")
    roots = {row["module"]: row["resolvedRoots"] for row in maps}
    operations = tests = 0
    for row in maps:
        module = row["module"]
        need(row.get("schema") == "hepta.module-implementation-map.v2" and row.get("schemaVersion") == 2, f"{module}: schema")
        need(row.get("repositoryControlledGaps") == [], f"{module}: repository gaps")
        need(row.get("externalEvidenceGates"), f"{module}: external gates")
        for root in row["resolvedRoots"]: need((ROOT / root).exists(), f"{module}: missing root {root}")
        for item in row["operations"]:
            operations += 1
            need(item.get("mappingClass") in truth["allowedMappingClasses"], f"{module}: mapping class")
            verify_anchor(module, row["resolvedRoots"], item["ownerEntrypoint"], True)
            for delegate in item.get("delegatedCallees", []):
                verify_anchor(module, row["resolvedRoots"], delegate, False)
                owner = delegate["ownerModule"]
                need(owner in roots and any(delegate["path"] == root or delegate["path"].startswith(root + "/") for root in roots[owner]), f"{module}: delegate-root escape")
            need(item.get("tests"), f"{module}/{item['designOperation']}: tests")
            for test in item["tests"]:
                tests += 1
                need((ROOT / test["path"]).is_file() and test.get("command"), f"{module}: invalid test binding")
            need(len(item.get("sourceSemantics", "")) >= 40, f"{module}: source semantics")
        for path in (ROOT / f"docs/modules/{module}/TECHNICAL.md", ROOT / f"qualification/module-execution-dossiers/detail/{module}.md"):
            text = path.read_text(encoding="utf-8")
            need(module in text and not FORBIDDEN.search(text), f"{module}: document {path.relative_to(ROOT)}")
    need(operations == 39, "operation count")
    return operations, tests


def projections(truth: dict[str, Any], maps: list[dict[str, Any]]) -> dict[Path, str]:
    return {TRACE: dump(trace_projection(truth, maps)), NATIVE: native_projection(truth, maps)}


def verify_generated(truth: dict[str, Any], maps: list[dict[str, Any]]) -> None:
    for path, expected in projections(truth, maps).items():
        need(path.read_text(encoding="utf-8") == expected, f"projection drift: {path.relative_to(ROOT)}")
    composition = COMPOSITION.read_text(encoding="utf-8")
    base = truth["sourceBase"]
    need(base["commit"] in composition and base["tree"] in composition, "composition base")
    need("product execution" in composition.lower() and "independent acceptance" in composition.lower(), "composition claims")
    need("hepta-lane-b-truth.py verify" in README.read_text(encoding="utf-8"), "README command")


def generate(truth: dict[str, Any], maps: list[dict[str, Any]]) -> int:
    for path, content in projections(truth, maps).items(): path.write_text(content, encoding="utf-8")
    print(json.dumps({"status": "GENERATED_HEPTA_LANE_B_PROJECTIONS", "files": 2}, sort_keys=True))
    return 0


def verify() -> int:
    truth = load(TRUTH); maps = module_maps(truth)
    changed = verify_candidate(load(MANIFEST), truth)
    operations, tests = verify_truth(truth, maps); verify_generated(truth, maps)
    print(json.dumps({
        "status": "PASS_HEPTA_LANE_B_SOURCE_CLOSURE", "exactHead": git("rev-parse", "HEAD"),
        "exactTree": git("rev-parse", "HEAD^{tree}"), "changedPaths": len(changed),
        "modules": len(maps), "operations": operations, "testBindings": tests,
        "repositoryControlledSourceBoundaryGapsClosed": True, "productExecutionComplete": False,
        "externalEffectsComplete": False, "independentAcceptanceComplete": False,
    }, sort_keys=True))
    return 0


def self_test() -> int:
    need(pairs([("a", 1), ("b", 2)]) == {"a": 1, "b": 2}, "pairs")
    try: pairs([("a", 1), ("a", 2)])
    except Invalid: pass
    else: raise Invalid("duplicate key accepted")
    need(allowed("qualification/lane-b/a", ["qualification/lane-b/"]), "allow")
    need(not allowed("qualification/lane-c/a", ["qualification/lane-b/"]), "deny")
    need(len(MODULES) == 11 and sum(map(len, OPS.values())) == 39, "closed sets")
    print(json.dumps({"status": "PASS_HEPTA_LANE_B_SOURCE_CLOSURE_SELF_TEST", "modules": 11, "operations": 39}, sort_keys=True))
    return 0


def main() -> int:
    command = argparse.ArgumentParser(); command.add_argument("command", choices=["verify", "generate", "self-test"])
    action = command.parse_args().command
    if action == "self-test": return self_test()
    truth = load(TRUTH); maps = module_maps(truth)
    return generate(truth, maps) if action == "generate" else verify()


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Invalid as exc: raise SystemExit(f"FAIL_HEPTA_LANE_B_SOURCE_CLOSURE: {exc}") from exc
