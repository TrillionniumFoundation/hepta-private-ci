#!/usr/bin/env python3
"""Focused, exact-candidate verifier for learning.plasticity machine bindings.

This verifier deliberately does not inspect unrelated module maps. It proves the
learning.plasticity operation/source/test bindings against the checked-out Git
objects and rejects legacy hidden-source/materializer workflows.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_source(identity: str) -> tuple[str, str]:
    if ".rs::" not in identity:
        raise ValueError(f"invalid Rust test identity: {identity!r}")
    source, symbol = identity.split(".rs::", 1)
    return source + ".rs", symbol.rsplit("::", 1)[-1]


def main() -> int:
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("dirty candidate")

    row = load("docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json")
    if row.get("schema") != "hepta.module-implementation-map.v3" or row.get("module") != "learning.plasticity":
        raise SystemExit("implementation-map identity/schema mismatch")
    anchor = row.get("sourceBase") or {}
    if not re.fullmatch(r"[0-9a-f]{40}", str(anchor.get("commit", ""))):
        raise SystemExit("invalid sourceBase commit")
    if not re.fullmatch(r"[0-9a-f]{40}", str(anchor.get("tree", ""))):
        raise SystemExit("invalid sourceBase tree")
    if git("rev-parse", f"{anchor['commit']}^{{tree}}") != anchor["tree"]:
        raise SystemExit("sourceBase commit/tree mismatch")
    subprocess.run(["git", "merge-base", "--is-ancestor", anchor["commit"], head], cwd=ROOT, check=True)

    boundary = row.get("claimBoundary") or {}
    for claim in ("productionImplementation", "productExecutionProved", "independentAcceptance", "activation", "release"):
        if boundary.get(claim) is not False:
            raise SystemExit(f"unsupported execution claim: {claim}")

    required = {
        "parameter_generator_coverage",
        "topology_generator_coverage",
        "control_engineering_parameter_iteration_coordinator",
        "control_engineering_topology_iteration_coordinator",
    }
    operations = row.get("operations")
    if not isinstance(operations, list) or not operations:
        raise SystemExit("empty operation inventory")
    names = {op.get("operation") for op in operations}
    if not required <= names:
        raise SystemExit(f"missing operations: {sorted(required - names)}")

    bound_paths: set[str] = set()
    for op in operations:
        name = op.get("operation")
        source = op.get("sourcePath")
        symbol = op.get("nativeSymbol")
        tests = op.get("tests")
        if not all(isinstance(value, str) and value for value in (name, source, symbol)):
            raise SystemExit(f"incomplete operation binding: {name!r}")
        source_path = ROOT / source
        if not source_path.is_file():
            raise SystemExit(f"missing operation source: {source}")
        source_text = source_path.read_text(encoding="utf-8")
        leaf = symbol.rsplit("::", 1)[-1]
        if leaf not in source_text:
            raise SystemExit(f"unresolved operation symbol: {name} -> {symbol}")
        if not isinstance(tests, list) or not tests:
            raise SystemExit(f"operation has no focused tests: {name}")
        bound_paths.add(source)
        for identity in tests:
            path, test = test_source(identity)
            candidate = ROOT / path
            if not candidate.is_file():
                raise SystemExit(f"missing test source: {path}")
            if re.search(rf"\bfn\s+{re.escape(test)}\s*\(", candidate.read_text(encoding="utf-8")) is None:
                raise SystemExit(f"unresolved test identity: {identity}")
            bound_paths.add(path)

    callers = row.get("productCallers")
    if not isinstance(callers, list) or len(callers) < 4:
        raise SystemExit("parameter/topology coordinator caller bindings are incomplete")
    for caller in callers:
        path = caller.get("sourcePath")
        symbol = caller.get("nativeSymbol")
        if not isinstance(path, str) or not isinstance(symbol, str):
            raise SystemExit("invalid product caller binding")
        candidate = ROOT / path
        if not candidate.is_file() or symbol.rsplit("::", 1)[-1] not in candidate.read_text(encoding="utf-8"):
            raise SystemExit(f"unresolved product caller: {path}::{symbol}")
        bound_paths.add(path)

    objects = row.get("sourceObjects")
    if not isinstance(objects, list) or not objects:
        raise SystemExit("missing exact source object manifest")
    object_map = {item.get("path"): item.get("object") for item in objects if isinstance(item, dict)}
    for path in bound_paths:
        expected = object_map.get(path)
        actual = git("rev-parse", f"HEAD:{path}")
        if expected != actual:
            raise SystemExit(f"source/test blob drift: {path}: expected={expected} actual={actual}")
    observed = set(row.get("observedSourcePaths") or [])
    if not bound_paths <= observed:
        raise SystemExit(f"observed source inventory omits: {sorted(bound_paths - observed)}")
    changed = git("diff", "--name-only", anchor["commit"], head, "--", *sorted(observed))
    if changed:
        raise SystemExit("mapped evidence changed after sourceBase: " + changed.replace("\n", ", "))

    state = load("docs/modules/learning.plasticity/CURRENT_STATE.json")
    if state.get("sourceBase") != anchor:
        raise SystemExit("CURRENT_STATE sourceBase differs from implementation map")
    current = state.get("current") or {}
    for claim in ("productionImplementation",):
        if current.get(claim) is not False:
            raise SystemExit(f"CURRENT_STATE overclaim: {claim}")
    status = (ROOT / "docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md").read_text(encoding="utf-8")
    if row["productCallerState"] not in status:
        raise SystemExit("generated current-implementation status is stale")
    for operation in required:
        if f"`{operation}`" not in status:
            raise SystemExit(f"current-implementation status omits {operation}")

    hidden = []
    authoring = ROOT / ".authoring"
    if authoring.is_dir():
        for item in authoring.iterdir():
            if item.is_file() and ("plasticity" in item.name or item.name.startswith("review-p1-core")):
                hidden.append(str(item.relative_to(ROOT)))
    if hidden:
        raise SystemExit("hidden plasticity source remains: " + ", ".join(sorted(hidden)))
    write_workflows = []
    for workflow in (ROOT / ".github/workflows").glob("*plasticity*.yml"):
        text = workflow.read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*contents:\s*write\s*$", text):
            write_workflows.append(str(workflow.relative_to(ROOT)))
        if ".authoring/" in text or "git reset --hard" in text or "git push" in text:
            write_workflows.append(str(workflow.relative_to(ROOT)))
    if write_workflows:
        raise SystemExit("mutating/materializing qualification workflow remains: " + ", ".join(sorted(set(write_workflows))))

    print(json.dumps({
        "status": "PASS_LEARNING_PLASTICITY_EXACT_BINDINGS",
        "candidateCommit": head,
        "candidateTree": tree,
        "sourceBase": anchor,
        "operations": len(operations),
        "sourceObjects": len(objects),
        "executionClaims": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
