#!/usr/bin/env python3
"""Verify explicit intelligence.control requirement-to-test traceability.

Unlike the broad source inventory, this verifier does not infer coverage from
substring matches. Every requirement names exact source symbols and exact Rust
tests, including integration tests below `tests/`. Source presence and test
execution remain separate facts; the independent workflow records execution.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/modules/intelligence.control/REQUIREMENT_MATRIX.json"
TEST_RE = re.compile(
    r"(?P<attrs>(?:\s*#\[[^\n]+\]\s*)+)(?:async\s+)?fn\s+(?P<name>[A-Za-z0-9_]+)\s*\(",
    re.MULTILINE,
)


def load_matrix() -> dict[str, Any]:
    value = json.loads(MATRIX.read_text(encoding="utf-8"))
    if value.get("schema") != "hepta.intelligence-control-requirements.v1":
        raise SystemExit("invalid intelligence.control requirement-matrix schema")
    return value


def discover_tests() -> dict[tuple[str, str], dict[str, Any]]:
    roots = [
        ROOT / "codex-rs/hepta-intelligence/src",
        ROOT / "codex-rs/hepta-intelligence/tests",
        ROOT / "codex-rs/hepta-agentd/src",
        ROOT / "codex-rs/hepta-infer-worker-host/src",
        ROOT / "codex-rs/hepta-infer-worker-host/tests",
    ]
    tests: dict[tuple[str, str], dict[str, Any]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.rs")):
            text = path.read_text(encoding="utf-8")
            relative = path.relative_to(ROOT).as_posix()
            for match in TEST_RE.finditer(text):
                attrs = match.group("attrs")
                if "test" not in attrs:
                    continue
                key = (relative, match.group("name"))
                if key in tests:
                    raise SystemExit(f"duplicate test identity: {relative}::{key[1]}")
                tests[key] = {
                    "ignored": "ignore" in attrs,
                    "qualificationOnly": "qualification-" in attrs
                    or "qualification-" in text[max(0, match.start() - 700) : match.start()],
                }
    return tests


def require_source(entry: dict[str, Any], errors: list[str]) -> None:
    path = ROOT / entry["path"]
    if not path.is_file():
        errors.append(f"missing source file {entry['path']}")
        return
    text = path.read_text(encoding="utf-8")
    symbol = entry["symbol"]
    if symbol not in text:
        errors.append(f"missing source symbol {entry['path']}::{symbol}")


def verify() -> None:
    matrix = load_matrix()
    tests = discover_tests()
    errors: list[str] = []
    requirement_ids: set[str] = set()
    referenced_tests: set[tuple[str, str]] = set()

    requirements = matrix.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise SystemExit("requirement matrix must contain requirements")

    for requirement in requirements:
        requirement_id = requirement.get("id")
        if not isinstance(requirement_id, str) or not requirement_id:
            errors.append("requirement omitted id")
            continue
        if requirement_id in requirement_ids:
            errors.append(f"duplicate requirement id {requirement_id}")
        requirement_ids.add(requirement_id)

        sources = requirement.get("sources", [])
        mapped_tests = requirement.get("tests", [])
        if not sources:
            errors.append(f"{requirement_id}: no source mapping")
        if not mapped_tests:
            errors.append(f"{requirement_id}: no test mapping")
        for source in sources:
            require_source(source, errors)
        for test in mapped_tests:
            key = (test["path"], test["name"])
            referenced_tests.add(key)
            discovered = tests.get(key)
            if discovered is None:
                errors.append(f"{requirement_id}: missing test {key[0]}::{key[1]}")
                continue
            if discovered["ignored"]:
                errors.append(f"{requirement_id}: ignored test cannot satisfy requirement {key[1]}")
            expected_class = test.get("class", "product")
            if expected_class == "product" and discovered["qualificationOnly"]:
                errors.append(
                    f"{requirement_id}: qualification-only test mapped as product {key[1]}"
                )

    required_test_names = set(matrix.get("requiredTestNames", []))
    mapped_names = {name for _, name in referenced_tests}
    for name in sorted(required_test_names - mapped_names):
        errors.append(f"required test is not mapped to a requirement: {name}")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        raise SystemExit(1)

    print(
        json.dumps(
            {
                "requirements": len(requirement_ids),
                "mappedTests": len(referenced_tests),
                "discoveredTests": len(tests),
                "integrationTestsMapped": sum("/tests/" in path for path, _ in referenced_tests),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        parser.error("--check is required")
    verify()


if __name__ == "__main__":
    main()
