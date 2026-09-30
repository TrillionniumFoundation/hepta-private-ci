#!/usr/bin/env python3
"""Verify exact learning.plasticity source, symbol, test, and object bindings.

The committed implementation map binds an immutable authored source base. Exact
source-head, deterministic-merge, GitHub synthetic-merge, and final-merge SHAs are
bound at qualification time in non-stitchable receipts. This avoids an impossible
self-referential requirement for a committed file to contain its own commit SHA.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
MODULE = "learning.plasticity"
MAP_PATH = "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
STATE_PATH = "docs/modules/learning.plasticity/CURRENT_STATE.json"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_source(identity: str) -> tuple[str, str]:
    if ".rs::" not in identity:
        raise ValueError(f"invalid Rust test identity: {identity!r}")
    source, symbol = identity.split(".rs::", 1)
    return source + ".rs", symbol.rsplit("::", 1)[-1]


def symbol_present(text: str, symbol: str) -> bool:
    leaf = symbol.rsplit("::", 1)[-1]
    patterns = (
        rf"\b(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+{re.escape(leaf)}\s*\(",
        rf"\b(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|const|static|mod)\s+{re.escape(leaf)}\b",
    )
    return any(re.search(pattern, text) is not None for pattern in patterns)


def object_at(revision: str, path: str) -> str:
    return git("rev-parse", f"{revision}:{path}")


def main() -> int:
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("dirty candidate")

    row = load(MAP_PATH)
    if row.get("schema") != "hepta.module-implementation-map.v3" or row.get("module") != MODULE:
        raise SystemExit("implementation-map identity/schema mismatch")
    if row.get("sourceIdentityPolicy") != "authored_source_base_plus_runtime_exact_candidate_v1":
        raise SystemExit("unsupported source identity policy")

    anchor = row.get("sourceBase") or {}
    anchor_commit = str(anchor.get("commit", ""))
    anchor_tree = str(anchor.get("tree", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", anchor_commit):
        raise SystemExit("invalid sourceBase commit")
    if not re.fullmatch(r"[0-9a-f]{40}", anchor_tree):
        raise SystemExit("invalid sourceBase tree")
    if git("rev-parse", f"{anchor_commit}^{{tree}}") != anchor_tree:
        raise SystemExit("sourceBase commit/tree mismatch")

    observed_at = row.get("observedAtHead") or {}
    if observed_at != anchor:
        raise SystemExit("observedAtHead must identify the immutable authored source base")

    boundary = row.get("claimBoundary") or {}
    for claim in (
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    ):
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

    objects = row.get("sourceObjects")
    if not isinstance(objects, list) or not objects:
        raise SystemExit("missing exact source object manifest")
    object_map: dict[str, str] = {}
    for item in objects:
        if not isinstance(item, dict):
            raise SystemExit("invalid source object row")
        path = item.get("path")
        object_id = item.get("object")
        if not isinstance(path, str) or not path or not re.fullmatch(r"[0-9a-f]{40}", str(object_id or "")):
            raise SystemExit(f"invalid source object binding: {item!r}")
        if path in object_map:
            raise SystemExit(f"duplicate source object binding: {path}")
        object_map[path] = object_id
        actual = object_at("HEAD", path)
        if object_id != actual:
            raise SystemExit(f"source object drift: {path}: expected={object_id} actual={actual}")

    observed = set(row.get("observedSourcePaths") or [])
    if observed != set(object_map):
        raise SystemExit("observed source paths and source object manifest differ")

    bound_paths: set[str] = set()
    for op in operations:
        name = op.get("operation")
        source = op.get("sourcePath")
        symbol = op.get("nativeSymbol")
        tests = op.get("tests")
        if not all(isinstance(value, str) and value for value in (name, source, symbol)):
            raise SystemExit(f"incomplete operation binding: {name!r}")
        if op.get("module") != MODULE or op.get("operationId") != name:
            raise SystemExit(f"operation identity drift: {name}")
        if op.get("sourceSymbol") != symbol:
            raise SystemExit(f"source symbol binding drift: {name}")
        if op.get("candidateCommitSha") != anchor_commit:
            raise SystemExit(f"candidate commit binding drift: {name}")

        source_path = ROOT / source
        if not source_path.is_file():
            raise SystemExit(f"missing operation source: {source}")
        source_text = source_path.read_text(encoding="utf-8")
        if not symbol_present(source_text, symbol):
            raise SystemExit(f"unresolved operation symbol: {name} -> {symbol}")
        source_blob = object_at("HEAD", source)
        if op.get("sourceBlobSha") != source_blob or object_map.get(source) != source_blob:
            raise SystemExit(f"source blob binding drift: {name} -> {source}")
        if not isinstance(tests, list) or not tests:
            raise SystemExit(f"operation has no focused tests: {name}")

        bindings = op.get("testBindings")
        if not isinstance(bindings, list) or len(bindings) != len(tests):
            raise SystemExit(f"test binding inventory drift: {name}")
        bound_paths.add(source)
        for identity, binding in zip(tests, bindings, strict=True):
            path, test = test_source(identity)
            candidate = ROOT / path
            if not candidate.is_file():
                raise SystemExit(f"missing test source: {path}")
            if re.search(rf"\bfn\s+{re.escape(test)}\s*\(", candidate.read_text(encoding="utf-8")) is None:
                raise SystemExit(f"unresolved test identity: {identity}")
            test_blob = object_at("HEAD", path)
            expected_binding = {"target": path, "symbol": test, "blobSha": test_blob}
            if binding != expected_binding or object_map.get(path) != test_blob:
                raise SystemExit(f"test object binding drift: {identity}")
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
        if not candidate.is_file() or not symbol_present(candidate.read_text(encoding="utf-8"), symbol):
            raise SystemExit(f"unresolved product caller: {path}::{symbol}")
        if object_map.get(path) != object_at("HEAD", path):
            raise SystemExit(f"product caller object drift: {path}")
        bound_paths.add(path)

    if not bound_paths <= observed:
        raise SystemExit(f"observed source inventory omits: {sorted(bound_paths - observed)}")

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", anchor_commit, head],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    if ancestor:
        changed = git("diff", "--name-only", anchor_commit, head, "--", *sorted(observed))
        if changed:
            raise SystemExit("mapped evidence changed after sourceBase: " + changed.replace("\n", ", "))
    # A squash/rebase final merge need not retain anchor ancestry. Exact object
    # equivalence above is the admissible alternate proof; every observed path,
    # including the declared source-root tree, must still match.

    state = load(STATE_PATH)
    if state.get("sourceBase") != anchor:
        raise SystemExit("CURRENT_STATE sourceBase differs from implementation map")
    current = state.get("current") or {}
    if current.get("productionImplementation") is not False:
        raise SystemExit("CURRENT_STATE overclaim: productionImplementation")
    claim_boundary = current.get("claimBoundary") or {}
    for claim in (
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    ):
        if claim_boundary.get(claim) is not False:
            raise SystemExit(f"CURRENT_STATE overclaim: {claim}")

    status = (ROOT / "docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md").read_text(
        encoding="utf-8"
    )
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
        raise SystemExit(
            "mutating/materializing qualification workflow remains: "
            + ", ".join(sorted(set(write_workflows)))
        )

    print(
        json.dumps(
            {
                "status": "PASS_LEARNING_PLASTICITY_EXACT_BINDINGS",
                "candidateCommit": head,
                "candidateTree": tree,
                "sourceBase": anchor,
                "sourceBaseIsAncestor": ancestor,
                "exactObjectEquivalence": True,
                "operations": len(operations),
                "sourceObjects": len(objects),
                "executionClaims": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
