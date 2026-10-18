#!/usr/bin/env python3
"""Verify learning.plasticity operation/source/test identities at the exact checkout.

The tracked implementation map records durable navigation/provenance. This verifier
binds those declarations, plus the candidate overlay, to the exact Git commit under
qualification. It never rewrites source or generated documents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
OVERLAY = ROOT / "docs/modules/learning.plasticity/EXACT_MAPPING.json"
FORBIDDEN_WORKFLOWS = {
    ".github/workflows/learning-plasticity-materialized-source-diagnostic.yml",
    ".github/workflows/learning-plasticity-p0-materialize.yml",
    ".github/workflows/learning-plasticity-p1-apply.yml",
    ".github/workflows/learning-plasticity-review-snapshot.yml",
    ".github/workflows/learning-plasticity-source-materialize.yml",
}


def git(*args: str, input_text: str | None = None) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.check_output(
        ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        text=True,
        input=input_text,
    ).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain one JSON object")
    return value


def declaration_exists(text: str, symbol: str) -> bool:
    leaf = symbol.rsplit("::", 1)[-1]
    leaf = leaf.split("<", 1)[0].strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", leaf):
        return False
    patterns = (
        rf"\b(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+{re.escape(leaf)}\s*(?:<[^>]*>\s*)?\(",
        rf"\b(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|union)\s+{re.escape(leaf)}\b",
        rf"\b(?:pub(?:\([^)]*\))?\s+)?(?:const|static)\s+{re.escape(leaf)}\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def split_test_identity(identity: str) -> tuple[str, str]:
    marker = ".rs::"
    if marker not in identity:
        raise ValueError(f"Rust test identity lacks '.rs::': {identity!r}")
    source, symbol = identity.split(marker, 1)
    path = source + ".rs"
    leaf = symbol.rsplit("::", 1)[-1]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", leaf):
        raise ValueError(f"invalid Rust test symbol: {identity!r}")
    return path, leaf


def blob_at_head(path: str) -> str:
    value = git("rev-parse", f"HEAD:{path}")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"invalid blob identity for {path}")
    return value


def merge_operations(base: dict[str, Any], overlay: dict[str, Any]) -> list[dict[str, Any]]:
    ordered: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in base.get("operations", []):
        if not isinstance(row, dict) or not isinstance(row.get("operation"), str):
            raise ValueError("implementation-map operations must be typed and named")
        operation = row["operation"]
        if operation in by_id:
            raise ValueError(f"duplicate operation: {operation}")
        ordered.append(operation)
        by_id[operation] = dict(row)
    for row in overlay.get("operations", []):
        if not isinstance(row, dict) or not isinstance(row.get("operation"), str):
            raise ValueError("exact overlay operations must be typed and named")
        operation = row["operation"]
        if operation not in by_id:
            ordered.append(operation)
            by_id[operation] = {}
        by_id[operation].update(row)
    return [by_id[operation] for operation in ordered]


def reject_hidden_source() -> None:
    tracked = git("ls-files", ".authoring", "scripts").splitlines()
    offenders = [
        path
        for path in tracked
        if (path.startswith(".authoring/") and (
            "plasticity" in path.lower() or "review-p1-core" in path.lower()
        ))
        or path.startswith("scripts/.learning_plasticity_phase_timing.part")
    ]
    if offenders:
        raise ValueError("hidden plasticity source remains tracked: " + ", ".join(offenders))
    workflow_offenders = [path for path in sorted(FORBIDDEN_WORKFLOWS) if (ROOT / path).exists()]
    if workflow_offenders:
        raise ValueError(
            "source-mutating plasticity workflow remains: " + ", ".join(workflow_offenders)
        )


def inventory_identity(rows: list[dict[str, Any]]) -> str:
    semantic_rows = []
    for row in rows:
        semantic = dict(row)
        semantic.pop("candidateCommitSha", None)
        semantic_rows.append(semantic)
    encoded = json.dumps(
        semantic_rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if root != ROOT.resolve():
        raise SystemExit("script/repository root mismatch")
    candidate = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    expected = os.environ.get("TESTED_SHA")
    if expected and candidate != expected:
        raise SystemExit(f"expected {expected}, observed {candidate}")
    if git("status", "--porcelain"):
        raise SystemExit("exact mapping requires a completely clean checkout")

    reject_hidden_source()
    base = load(MAP)
    overlay = load(OVERLAY)
    if base.get("module") != "learning.plasticity" or overlay.get("module") != "learning.plasticity":
        raise SystemExit("module identity mismatch")
    caller_state = overlay.get("productCallerState", "")
    if not isinstance(caller_state, str) or "not_product_composed" in caller_state:
        raise SystemExit("exact overlay does not close the production caller source mapping")

    operations = merge_operations(base, overlay)
    if not operations:
        raise SystemExit("empty operation inventory")

    source_cache: dict[str, str] = {}
    test_cache: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for operation in operations:
        operation_id = operation.get("operation")
        source_path = operation.get("sourcePath")
        source_symbol = operation.get("nativeSymbol")
        tests = operation.get("tests")
        if not all(isinstance(value, str) and value for value in (operation_id, source_path, source_symbol)):
            raise SystemExit(f"incomplete operation mapping: {operation_id!r}")
        if not isinstance(tests, list) or not tests or any(not isinstance(test, str) for test in tests):
            raise SystemExit(f"{operation_id}: focused Rust test identities are required")

        source = ROOT / source_path
        if not source.is_file():
            raise SystemExit(f"{operation_id}: missing source {source_path}")
        source_text = source_cache.setdefault(source_path, source.read_text(encoding="utf-8"))
        if not declaration_exists(source_text, source_symbol):
            raise SystemExit(
                f"{operation_id}: source symbol {source_symbol!r} is not declared in {source_path}"
            )
        source_blob = blob_at_head(source_path)

        bound_tests = []
        for identity in tests:
            test_path, test_symbol = split_test_identity(identity)
            path = ROOT / test_path
            if not path.is_file():
                raise SystemExit(f"{operation_id}: missing test source {test_path}")
            text = test_cache.setdefault(test_path, path.read_text(encoding="utf-8"))
            if re.search(rf"\bfn\s+{re.escape(test_symbol)}\s*\(", text) is None:
                raise SystemExit(
                    f"{operation_id}: test identity {identity!r} does not name a function"
                )
            bound_tests.append(
                {
                    "testTarget": test_path,
                    "testSymbol": test_symbol,
                    "testBlobSha": blob_at_head(test_path),
                }
            )
        rows.append(
            {
                "module": "learning.plasticity",
                "operationId": operation_id,
                "sourcePath": source_path,
                "sourceSymbol": source_symbol,
                "sourceBlobSha": source_blob,
                "candidateCommitSha": candidate,
                "tests": bound_tests,
            }
        )

    docs = sorted(
        path
        for path in (
            "docs/modules/learning.plasticity/TECHNICAL.md",
            "docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md",
            "docs/modules/learning.plasticity/CURRENT_STATE.json",
            "docs/modules/learning.plasticity/CURRENT_CANDIDATE.md",
            "docs/modules/learning.plasticity/OPERATIONS.md",
            "docs/modules/learning.plasticity/ALGORITHM.md",
            "docs/modules/learning.plasticity/TARGET_HOST_QUALIFICATION.md",
        )
        if (ROOT / path).is_file()
    )
    documentation_hash = hashlib.sha256()
    for path in docs:
        documentation_hash.update(path.encode("utf-8") + b"\0")
        documentation_hash.update((ROOT / path).read_bytes())

    receipt = {
        "schema": "hepta.learning-plasticity-exact-mapping.v1",
        "module": "learning.plasticity",
        "candidateCommitSha": candidate,
        "candidateTreeSha": tree,
        "historicalSourceBase": base.get("sourceBase"),
        "trackedImplementationMapSha256": sha256(MAP),
        "exactOverlaySha256": sha256(OVERLAY),
        "cargoLockSha256": sha256(ROOT / "codex-rs/Cargo.lock"),
        "documentationSha256": documentation_hash.hexdigest(),
        "productCallerState": caller_state,
        "productionImplementation": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "operations": rows,
        "testInventorySha256": inventory_identity(rows),
    }
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise SystemExit("exact mapping receipt must be written outside the candidate checkout")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(receipt["testInventorySha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
