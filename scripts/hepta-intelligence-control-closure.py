#!/usr/bin/env python3
"""Verify explicit intelligence.control requirement/source/test traceability.

This verifier deliberately does not infer semantic coverage from filename or
function-name similarity. Each requirement names exact source symbols and exact
test functions. Execution status remains owned by the current GitHub Actions
command records; this script validates only the closed-world mapping itself.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "docs/modules/intelligence.control/REQUIREMENT_TEST_MAP.json"
ALLOWED_SOURCE_ROOTS = (
    "codex-rs/hepta-intelligence/",
    "codex-rs/hepta-agentd/",
    "codex-rs/hepta-infer-worker-host/",
    "codex-rs/hepta-operations/",
    "docs/modules/intelligence.control/",
    "scripts/",
)
TEST_PATTERN = re.compile(
    r"(?P<attrs>(?:\s*#\[[^\n]+\]\s*)+)"
    r"(?:async\s+)?fn\s+(?P<name>[A-Za-z0-9_]+)\s*\(",
    re.MULTILINE,
)


def fail(message: str) -> None:
    raise SystemExit(f"intelligence.control closure map: {message}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot load {path.relative_to(ROOT)}: {error}")
    if not isinstance(value, dict):
        fail("mapping root must be an object")
    return value


def checked_path(relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        fail("source/test path must be a non-empty string")
    if relative.startswith("/") or ".." in Path(relative).parts:
        fail(f"unsafe path: {relative}")
    if not relative.startswith(ALLOWED_SOURCE_ROOTS):
        fail(f"path is outside intelligence closure roots: {relative}")
    path = ROOT / relative
    if not path.is_file():
        fail(f"missing mapped file: {relative}")
    return path


def discovered_tests(path: Path) -> dict[str, bool]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, bool] = {}
    for match in TEST_PATTERN.finditer(text):
        attrs = match.group("attrs")
        if "test" not in attrs:
            continue
        name = match.group("name")
        if name in result:
            fail(f"duplicate test function {name} in {path.relative_to(ROOT)}")
        result[name] = "ignore" in attrs
    return result


def main() -> None:
    value = load_json(MAPPING)
    if value.get("schema") != "hepta.intelligence-control-requirement-test-map.v1":
        fail("unexpected schema")
    if value.get("schemaVersion") != 1 or value.get("module") != "intelligence.control":
        fail("unexpected schema version or module")
    if value.get("generated") is not False:
        fail("the mapping must remain human-reviewed, not generator-issued")

    claim = value.get("claimBoundary")
    if not isinstance(claim, dict):
        fail("claimBoundary must be an object")
    forbidden_true = [
        "sourcePresenceIsExecutionEvidence",
        "ancestorResultsApplyToCurrentHead",
        "queuedOrSkippedCountsAsPassed",
        "realProcessE2EProved",
        "targetHostQualified",
        "activation",
        "release",
    ]
    for field in forbidden_true:
        if claim.get(field) is not False:
            fail(f"claim boundary {field} must remain false in tracked source")

    requirements = value.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        fail("requirements must be a non-empty list")

    ids: set[str] = set()
    mapped_tests: set[tuple[str, str]] = set()
    source_count = 0
    test_count = 0
    phases: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            fail("every requirement must be an object")
        requirement_id = requirement.get("id")
        if not isinstance(requirement_id, str) or not requirement_id.startswith("INT-"):
            fail("requirement id must be an INT-* string")
        if requirement_id in ids:
            fail(f"duplicate requirement id: {requirement_id}")
        ids.add(requirement_id)
        phase = requirement.get("phase")
        if phase not in {"A", "B", "C", "D"}:
            fail(f"invalid phase for {requirement_id}")
        phases.add(phase)
        statement = requirement.get("statement")
        if not isinstance(statement, str) or len(statement.strip()) < 20:
            fail(f"requirement {requirement_id} needs a substantive statement")

        sources = requirement.get("source")
        tests = requirement.get("tests")
        if not isinstance(sources, list) or not sources:
            fail(f"requirement {requirement_id} has no source anchors")
        if not isinstance(tests, list) or not tests:
            fail(f"requirement {requirement_id} has no tests")

        for anchor in sources:
            if not isinstance(anchor, dict):
                fail(f"invalid source anchor in {requirement_id}")
            relative = anchor.get("path")
            symbol = anchor.get("symbol")
            path = checked_path(relative)
            if not isinstance(symbol, str) or not symbol:
                fail(f"empty source symbol in {requirement_id}")
            if symbol not in path.read_text(encoding="utf-8"):
                fail(f"missing source symbol {symbol!r} in {relative}")
            source_count += 1

        for test in tests:
            if not isinstance(test, dict):
                fail(f"invalid test anchor in {requirement_id}")
            relative = test.get("path")
            name = test.get("name")
            path = checked_path(relative)
            if not isinstance(name, str) or not name:
                fail(f"empty test name in {requirement_id}")
            key = (relative, name)
            if key in mapped_tests:
                fail(f"test is mapped more than once: {relative}::{name}")
            mapped_tests.add(key)
            tests_in_file = discovered_tests(path)
            if name not in tests_in_file:
                fail(f"missing mapped test: {relative}::{name}")
            if tests_in_file[name]:
                fail(f"mapped test is ignored: {relative}::{name}")
            test_count += 1

    if phases != {"A", "B", "C", "D"}:
        fail(f"mapping must cover phases A-D exactly; found {sorted(phases)}")

    print(
        json.dumps(
            {
                "module": "intelligence.control",
                "requirements": len(ids),
                "sourceAnchors": source_count,
                "mappedTests": test_count,
                "phases": sorted(phases),
                "executionEvidence": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
