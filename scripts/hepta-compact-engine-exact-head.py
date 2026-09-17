#!/usr/bin/env python3
"""Generate exact-head compact.engine implementation/evidence map.

The checked-in IMPLEMENTATION_MAP is source-navigation evidence and cannot cite
its own future commit. This generator runs after the focused package tests and
emits an artifact bound to the exact checked-out HEAD/tree, discovered native
test cases, and the documented production consumer/writer callsite.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_ID = "compact.engine"
DOSSIER = ROOT / "qualification/module-execution-dossiers/detail/compact.engine.md"
MAP_PATH = ROOT / "docs/modules/compact.engine/IMPLEMENTATION_MAP.json"
MAP_SCRIPT = ROOT / "scripts/hepta-implementation-maps.py"


def git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return process.stdout.strip()


def load_map_module():
    spec = importlib.util.spec_from_file_location("hepta_implementation_maps", MAP_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load implementation-map generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rust_test_cases(text: str) -> list[str]:
    return sorted(
        set(
            re.findall(
                r"#\[(?:tokio::)?test(?:\([^]]*\))?\]\s*(?:async\s+)?fn\s+([A-Za-z0-9_]+)",
                text,
            )
        )
    )


def discover_tests(source: str | None, symbol: str | None) -> list[dict[str, object]]:
    if not source or not symbol:
        return []
    source_path = ROOT / source
    if not source_path.is_file():
        return []
    crate_root = source_path.parent.parent if source_path.parent.name == "src" else source_path.parent
    candidates = set(source_path.parent.glob("*_tests.rs"))
    source_text = source_path.read_text(encoding="utf-8")
    if "#[cfg(test)]" in source_text:
        candidates.add(source_path)
    tests_dir = crate_root / "tests"
    if tests_dir.is_dir():
        candidates.update(tests_dir.rglob("*.rs"))
    results: list[dict[str, object]] = []
    for path in sorted(candidates):
        text = path.read_text(encoding="utf-8")
        if symbol not in text:
            continue
        results.append(
            {
                "path": str(path.relative_to(ROOT)),
                "cases": rust_test_cases(text),
            }
        )
    return results


def parse_production_caller() -> dict[str, object] | None:
    text = DOSSIER.read_text(encoding="utf-8")
    match = re.search(
        r"\*\*Production caller:\*\*\s*`([^`]+)`\s+in\s+\[([^]]+)\]",
        text,
    )
    if not match:
        return None
    symbol, source = match.groups()
    if source.startswith("../../../"):
        source = source[9:]
    path = ROOT / source
    return {
        "symbol": symbol,
        "sourcePath": source,
        "sourcePathExists": path.is_file(),
        "ownerStore": "codex-hepta-memory/CognitiveStore",
        "authorityBoundary": "ProductionAuthorityVerifier",
        "state": "product_composed_owner_store" if path.is_file() else "missing",
        "tests": discover_tests(source, symbol),
    }


def build_exact_head_map(test_status: str, expected_sha: str | None) -> dict[str, object]:
    maps = load_map_module()
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if expected_sha and head != expected_sha:
        raise SystemExit(f"exact-head mismatch: expected {expected_sha}, checked out {head}")

    modules = maps.load("docs/modules/MODULES.json")["modules"]
    module = next(item for item in modules if item["id"] == MODULE_ID)
    row = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    exact = maps.migrate_map(row, module, maps.lane_by_module(), {"commit": head, "tree": tree})
    # migrate_map intentionally preserves historical evidence. Exact-head output
    # is a separate execution artifact and must bind the current checkout.
    exact["sourceBase"] = {"commit": head, "tree": tree}

    for operation in exact["operations"]:
        operation["tests"] = discover_tests(
            operation.get("sourcePath"), operation.get("nativeSymbol")
        )

    caller = parse_production_caller()
    exact["productionCaller"] = caller
    if caller and caller["sourcePathExists"]:
        exact["productionImplementation"] = True
        exact["productCallerState"] = "composed_owner_store"
        exact["productionWriterState"] = "established_owner_store"
        exact["claimBoundary"]["productionImplementation"] = True

    test_sources = sorted(
        {
            test["path"]
            for operation in exact["operations"]
            for test in operation.get("tests", [])
        }
        | {
            test["path"]
            for test in (caller or {}).get("tests", [])
        }
    )
    exact["exactHeadEvidence"] = {
        "schema": "hepta.compact-engine-exact-head-evidence.v1",
        "sourceSha": head,
        "sourceTree": tree,
        "focusedTestStatus": test_status,
        "focusedTestCommand": (
            "cargo test --locked -p codex-hepta-compact-engine -p codex-hepta-memory"
        ),
        "testSources": test_sources,
        "productionCallerObserved": bool(caller and caller["sourcePathExists"]),
        "generatedFrom": str(MAP_PATH.relative_to(ROOT)),
    }
    return exact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument(
        "--test-status",
        choices=["passed", "failed", "not_run"],
        default="not_run",
    )
    args = parser.parse_args()
    value = build_exact_head_map(args.test_status, args.expected_sha)
    rendered = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
