#!/usr/bin/env python3
"""Check prompt optimizer navigation and compiler/test-runner inventories.

Source-only checks do not prove compilation or execution. Qualification requires
rustc dep-info and nextest JSON from the same clean, exact-candidate build.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MODULE = "codex-rs/hepta-prompt-optimizer"
MAP_PATH = "docs/modules/prompt.optimizer/IMPLEMENTATION_MAP.json"
REQUIRED = {"enumerate_factors_v1", "price_factors_v1", "select_portfolio_v1", "exercise_v1", "build_verified_prompt_portfolio_v1"}
SEALED = {"EnumeratedPromptCandidatesV1", "PricedPromptCandidatesV1", "SelectedPromptPortfolioV1", "PromptExerciseDecisionV1"}


def unique_keys(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def checked_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError(f"invalid source path: {name!r}")
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"missing or escaped source path: {name!r}")
    return path


def source_checks(root: Path, row: dict) -> tuple[list[str], set[str]]:
    failures: list[str] = []
    tests: set[str] = set()
    operations = row.get("operations", [])
    if not isinstance(operations, list):
        raise ValueError("operations must be a list")
    names: set[str] = set()
    for operation in operations:
        name = operation.get("operation")
        if not isinstance(name, str) or name in names:
            raise ValueError("duplicate or invalid operation")
        names.add(name)
        source = checked_path(root, operation["sourcePath"])
        symbol = operation.get("nativeSymbol", "").rsplit("::", 1)[-1]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", symbol):
            failures.append(f"{name}: invalid native symbol")
        elif re.search(rf"\bpub(?:\([^)]*\))?\s+(?:async\s+)?fn\s+{re.escape(symbol)}\b", source.read_text()) is None:
            failures.append(f"{name}: native symbol is absent from mapped source")
        entries = operation.get("tests")
        if not isinstance(entries, list) or not entries:
            failures.append(f"{name}: no executable test identities mapped")
            continue
        for test in entries:
            if not isinstance(test, str) or ".rs::" not in test:
                failures.append(f"{name}: test must use source.rs::function form")
                continue
            path, leaf = test.split(".rs::", 1)
            source_test = checked_path(root, path + ".rs")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", leaf):
                failures.append(f"{name}: invalid test function")
            elif re.search(rf"#\[test\]\s*(?:async\s+)?fn\s+{re.escape(leaf)}\b", source_test.read_text()) is None:
                failures.append(f"{name}: {leaf} is not a source test")
            tests.add(leaf)
    for name in sorted(REQUIRED - names):
        failures.append(f"missing canonical operation: {name}")
    crate_root = checked_path(root, MODULE + "/src/lib.rs").read_text()
    if re.search(r"\bpub\s+mod\s+canonical_engine\s*;", crate_root):
        failures.append("raw arithmetic engine is externally callable")
    if not re.search(r"\bpub\s+mod\s+compat\s*;", crate_root):
        failures.append("compat namespace is absent")
    body = checked_path(root, MODULE + "/src/canonical_body.rs").read_text()
    for name in sorted(SEALED):
        match = re.search(rf"\bpub\s+struct\s+{name}\s*\{{([^}}]*)\}}", body, re.S)
        if match is None:
            failures.append(f"verified phase is absent: {name}")
        elif re.search(r"\bpub\b", match.group(1)):
            failures.append(f"verified phase exposes a field: {name}")
    if "DerefMut" in re.sub(r"//[^\n]*", "", body):
        failures.append("verified API exposes mutable dereferencing")
    if list((root / MODULE / "src").glob("policy*.rs")):
        failures.append("retired orphan policy implementation remains")
    return failures, tests


def compiled_sources(root: Path, dep_root: Path) -> set[str]:
    paths: set[str] = set()
    # Integration tests have their own crate names; scan every dep-info file,
    # then restrict the resulting dependency paths to this module's root.
    depfiles = sorted(dep_root.glob("*.d"))
    if not depfiles:
        raise ValueError("no rustc dep-info from a clean all-target build")
    for depfile in depfiles:
        text = depfile.read_text().replace("\\\n", "")
        first = next((line for line in text.splitlines() if ": " in line), "")
        if not first:
            continue
        dependencies = first.split(": ", 1)[1]
        for token in re.findall(r"(?:\\.|[^\s])+", dependencies):
            token = re.sub(r"\\(.)", r"\1", token)
            source = Path(token)
            if not source.is_absolute():
                source = root / "codex-rs" / source
            try:
                relative = str(source.resolve().relative_to(root.resolve()))
            except ValueError:
                continue
            if relative.startswith(MODULE + "/") and relative.endswith(".rs"):
                paths.add(relative)
    if not paths:
        raise ValueError("dep-info contains no compiled prompt optimizer source")
    return paths


def listed_test_leaves(path: Path) -> set[str]:
    data = json.loads(path.read_text(), object_pairs_hook=unique_keys)
    suites = data.get("rust-suites")
    if not isinstance(suites, dict) or not suites:
        raise ValueError("missing nextest rust-suites")
    tests: set[str] = set()
    for suite in suites.values():
        if suite.get("package-name") != "codex-hepta-prompt-optimizer":
            continue
        cases = suite.get("testcases")
        if not isinstance(cases, dict):
            raise ValueError("missing nextest testcases")
        for name, case in cases.items():
            if case.get("ignored"):
                continue
            tests.add(name.rsplit("::", 1)[-1])
    if not tests:
        raise ValueError("no non-ignored optimizer tests were listed")
    return tests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-only", action="store_true", help="navigation only, not compiled or test evidence")
    parser.add_argument("--dep-root", type=Path)
    parser.add_argument("--test-list", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        row = json.loads(checked_path(root, MAP_PATH).read_text(), object_pairs_hook=unique_keys)
        failures, tests = source_checks(root, row)
        if not args.source_only:
            if args.dep_root is None or args.test_list is None:
                raise ValueError("qualification requires --dep-root and --test-list")
            compiled = compiled_sources(root, args.dep_root)
            present = {str(path.relative_to(root)) for path in (root / MODULE).rglob("*.rs")}
            for path in sorted(present - compiled):
                failures.append(f"Rust source absent from compiler dep-info: {path}")
            listed = listed_test_leaves(args.test_list)
            for leaf in sorted(tests - listed):
                failures.append(f"mapped test not listed as non-ignored: {leaf}")
        identity = subprocess.run(["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=root,
                                  text=True, capture_output=True, check=True).stdout.splitlines()
        print(json.dumps({"module": "prompt.optimizer", "sourceOnly": args.source_only,
                          "commit": identity[0], "tree": identity[1], "mappedTests": len(tests),
                          "passed": not failures, "failures": failures}, indent=2))
        return int(bool(failures))
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL_PROMPT_OPTIMIZER_INVENTORY: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
