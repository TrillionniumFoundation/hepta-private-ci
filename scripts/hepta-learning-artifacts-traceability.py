#!/usr/bin/env python3
"""Fail-closed traceability validation for learning.artifacts.

Each requirement must name a real source symbol, one or more concrete test
functions, an exact qualification workflow step and a source object resolvable
from the candidate tree. Empty, duplicated, stale or prose-only mappings fail.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "qualification/learning.artifacts/TRACEABILITY.json"


def fail(message: str) -> None:
    raise SystemExit(f"learning.artifacts traceability: {message}")


def read_text(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        fail(f"missing file: {relative}")
    return path.read_text(encoding="utf-8")


def source_object(relative: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", f"HEAD:{relative}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"unresolvable source object: {relative}: {result.stderr.strip()}")
    value = result.stdout.strip()
    if len(value) != 40:
        fail(f"invalid source object for {relative}: {value!r}")
    return value


def main() -> int:
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    if data.get("schema") != "hepta.learning-artifacts.traceability.v1":
        fail("unexpected schema")
    if data.get("schemaVersion") != 1 or data.get("module") != "learning.artifacts":
        fail("unexpected module metadata")
    if data.get("authorityDelta") != "none":
        fail("traceability cannot grant authority")
    workflow_path = data.get("exactHeadWorkflow")
    if not isinstance(workflow_path, str) or not workflow_path:
        fail("missing exactHeadWorkflow")
    workflow = read_text(workflow_path)
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        fail("cases must be non-empty")

    identifiers: set[str] = set()
    output_cases: list[dict[str, object]] = []
    for case in cases:
        if not isinstance(case, dict):
            fail("case is not an object")
        case_id = case.get("id")
        requirement = case.get("requirement")
        if not isinstance(case_id, str) or not case_id or case_id in identifiers:
            fail(f"duplicate or empty case id: {case_id!r}")
        identifiers.add(case_id)
        if not isinstance(requirement, str) or len(requirement.strip()) < 24:
            fail(f"{case_id}: requirement is too weak")

        source = case.get("source")
        if not isinstance(source, dict):
            fail(f"{case_id}: missing source mapping")
        source_path = source.get("path")
        symbol = source.get("symbol")
        if not isinstance(source_path, str) or not isinstance(symbol, str) or not symbol:
            fail(f"{case_id}: invalid source mapping")
        source_text = read_text(source_path)
        if symbol not in source_text:
            fail(f"{case_id}: source symbol not found: {symbol} in {source_path}")

        tests = case.get("tests")
        if not isinstance(tests, list) or not tests:
            fail(f"{case_id}: no tests")
        mapped_tests: list[dict[str, str]] = []
        seen_tests: set[tuple[str, str]] = set()
        for test in tests:
            if not isinstance(test, dict):
                fail(f"{case_id}: invalid test mapping")
            test_path = test.get("path")
            function = test.get("function")
            if not isinstance(test_path, str) or not isinstance(function, str) or not function:
                fail(f"{case_id}: invalid test identity")
            identity = (test_path, function)
            if identity in seen_tests:
                fail(f"{case_id}: duplicate test identity: {identity}")
            seen_tests.add(identity)
            test_text = read_text(test_path)
            if f"fn {function}" not in test_text:
                fail(f"{case_id}: test function not found: {function} in {test_path}")
            mapped_tests.append(
                {"path": test_path, "function": function, "object": source_object(test_path)}
            )

        workflow_step = case.get("workflowStep")
        if not isinstance(workflow_step, str) or f"- name: {workflow_step}" not in workflow:
            fail(f"{case_id}: workflow step not found: {workflow_step!r}")
        output_cases.append(
            {
                "id": case_id,
                "source": {
                    "path": source_path,
                    "symbol": symbol,
                    "object": source_object(source_path),
                },
                "tests": mapped_tests,
                "workflowStep": workflow_step,
            }
        )

    output = {
        "schema": "hepta.learning-artifacts.traceability-verification.v1",
        "module": "learning.artifacts",
        "candidate": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "caseCount": len(output_cases),
        "workflow": {"path": workflow_path, "object": source_object(workflow_path)},
        "cases": output_cases,
        "ok": True,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
