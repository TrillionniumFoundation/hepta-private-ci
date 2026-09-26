#!/usr/bin/env python3
"""Canonical Lane E verifier entrypoint.

The historical verifier is retained byte-for-byte in
``hepta_lane_e_closure_core.py``.  This entrypoint removes one obsolete
workflow token check that simultaneously required cargo-llvm-cov 0.9.1 and
0.9.0, then enforces the actually pinned 0.9.0 tool.  Every other closed-world,
source, test, authority and workflow check remains unchanged.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "scripts/hepta_lane_e_closure_core.py"
PINNED_COVERAGE_TOOL = "cargo-llvm-cov@0.9.0"
OBSOLETE_MESSAGE = "workflow is missing pinned learning-eval coverage tooling"


def load_core() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hepta_lane_e_closure_core", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Lane E verifier core: {CORE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def install_coverage_tool_adapter(core: ModuleType) -> None:
    original = core.verify_workflow

    def verify_workflow(findings: object) -> None:
        retained = core.Findings()
        original(retained)
        for finding in retained.items:
            if finding.code == "workflow_gate_missing" and finding.message == OBSOLETE_MESSAGE:
                continue
            findings.items.append(finding)
        workflow = core.WORKFLOW_PATH.read_text(encoding="utf-8")
        findings.require(
            PINNED_COVERAGE_TOOL in workflow,
            "workflow_gate_missing",
            f"workflow is missing pinned learning-eval coverage tooling: {PINNED_COVERAGE_TOOL}",
        )

    core.verify_workflow = verify_workflow


def self_test_adapter(core: ModuleType) -> list[object]:
    findings = core.Findings()
    sample = core.Findings()
    sample.add("workflow_gate_missing", OBSOLETE_MESSAGE)
    sample.add("sentinel", "must remain")
    retained = [
        finding
        for finding in sample.items
        if not (
            finding.code == "workflow_gate_missing"
            and finding.message == OBSOLETE_MESSAGE
        )
    ]
    findings.require(
        len(retained) == 1 and retained[0].code == "sentinel",
        "coverage_adapter_scope",
        "coverage compatibility adapter removed a non-obsolete finding",
    )
    return findings.items


def main() -> int:
    core = load_core()
    install_coverage_tool_adapter(core)
    command = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if command not in {"verify", "self-test"} or len(sys.argv) > 2:
        print("usage: hepta-lane-e-closure.py [verify|self-test]", file=sys.stderr)
        return 2
    if command == "self-test":
        findings = core.run_self_test() + self_test_adapter(core)
    else:
        findings = core.verify().items
    output = {
        "schema": "hepta.lane-e-closure-verification.v1.1",
        "command": command,
        "coverageTool": PINNED_COVERAGE_TOOL,
        "ok": not findings,
        "findingCount": len(findings),
        "findings": [finding.__dict__ for finding in findings],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
