#!/usr/bin/env python3
"""Apply the remaining objective.compiler source changes.

Development-only edit. This script creates ordinary source changes and never
asserts qualification, target-host acceptance, activation, or release.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    text = read(path)
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(
            f"{path}: expected {count} occurrences, found {actual}: {old[:120]!r}"
        )
    write(path, text.replace(old, new))


def replace_after(
    path: str, marker: str, old: str, new: str, count: int = 1
) -> None:
    text = read(path)
    offset = text.find(marker)
    if offset < 0:
        raise RuntimeError(f"{path}: marker not found: {marker!r}")
    prefix, suffix = text[:offset], text[offset:]
    actual = suffix.count(old)
    if actual != count:
        raise RuntimeError(
            f"{path}: expected {count} occurrences after marker, found {actual}: {old[:120]!r}"
        )
    write(path, prefix + suffix.replace(old, new))


def append(path: str, content: str, sentinel: str) -> None:
    text = read(path)
    if sentinel in text:
        raise RuntimeError(f"{path}: sentinel already present: {sentinel}")
    write(path, text.rstrip() + "\n\n" + content.strip() + "\n")


# ---------------------------------------------------------------------------
# 3. Per-run evidence projection: actual receipts, never hand-edited pass flags.
# ---------------------------------------------------------------------------

write(
    "scripts/hepta-objective-evidence-project.py",
    r'''#!/usr/bin/env python3
"""Project objective.compiler execution artifacts into one traceable status view.

The projection is derived from observed receipts. It never grants independent
acceptance, activation, promotion, release, or selected deployment-host approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
LOG_SHA = re.compile(r"[0-9a-f]{64}\Z")


def load(path: Path) -> dict[str, Any]:
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_state(receipt: dict[str, Any], kind: str) -> str:
    candidates = receipt.get("candidates")
    if not isinstance(candidates, list):
        return "failed"
    matching = [
        item
        for item in candidates
        if isinstance(item, dict) and item.get("kind") == kind
    ]
    if len(matching) != 1:
        return "failed"
    candidate = matching[0]
    checks = candidate.get("checks")
    if (
        candidate.get("clean") is True
        and isinstance(checks, list)
        and checks
        and all(
            isinstance(check, dict)
            and check.get("status") == "completed"
            and check.get("exitCode") == 0
            and isinstance(check.get("logSha256"), str)
            and LOG_SHA.fullmatch(check["logSha256"])
            for check in checks
        )
    ):
        return "passed"
    return "failed"


def exact_projection(
    path: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("schema") != "hepta.objective.exact-execution.v1":
        raise ValueError("unexpected exact-execution schema")
    if (
        receipt.get("sourceCommit") != source_commit
        or receipt.get("sourceTree") != source_tree
    ):
        raise ValueError("exact-execution source identity mismatch")
    return {
        "artifactSha256": sha256(path),
        "runId": receipt.get("runId"),
        "runAttempt": receipt.get("runAttempt"),
        "workflowCommit": receipt.get("workflowCommit"),
        "sourceHeadQualification": candidate_state(receipt, "source-head"),
        "syntheticMergeQualification": candidate_state(receipt, "synthetic-merge"),
        "checksPassed": receipt.get("checksPassed") is True,
        "errors": receipt.get("errors")
        if isinstance(receipt.get("errors"), list)
        else [],
    }


def target_projection(
    path: Path, source_commit: str, source_tree: str
) -> dict[str, Any]:
    receipt = load(path)
    if receipt.get("schema") != "hepta.objective-target-host-evidence.v1":
        raise ValueError("unexpected target-measurement schema")
    if (
        receipt.get("sourceCommit") != source_commit
        or receipt.get("sourceTree") != source_tree
    ):
        raise ValueError("target-measurement source identity mismatch")
    measurements = receipt.get("measurements")
    observed = isinstance(measurements, list) and bool(measurements)
    return {
        "artifactSha256": sha256(path),
        "hostProfileId": receipt.get("hostProfileId"),
        "measurementObserved": observed,
        "measurementCount": len(measurements)
        if isinstance(measurements, list)
        else 0,
        "selectedDeploymentHostAccepted": False,
        "storageQualificationProved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--exact-execution", type=Path)
    parser.add_argument("--target-measurement", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not SHA.fullmatch(args.source_commit) or not SHA.fullmatch(args.source_tree):
        parser.error("source commit and tree must be complete lowercase SHA-1 identities")
    if args.exact_execution is None and args.target_measurement is None:
        parser.error("at least one evidence input is required")

    exact = (
        exact_projection(args.exact_execution, args.source_commit, args.source_tree)
        if args.exact_execution is not None
        else {
            "sourceHeadQualification": "unverified",
            "syntheticMergeQualification": "unverified",
            "checksPassed": False,
        }
    )
    target = (
        target_projection(args.target_measurement, args.source_commit, args.source_tree)
        if args.target_measurement is not None
        else {
            "measurementObserved": False,
            "selectedDeploymentHostAccepted": False,
            "storageQualificationProved": False,
        }
    )
    projection = {
        "schema": "hepta.objective-evidence-projection.v1",
        "module": "objective.compiler",
        "sourceCommit": args.source_commit,
        "sourceTree": args.source_tree,
        "exactExecution": exact,
        "targetHostMeasurement": target,
        "independentAcceptance": "unverified",
        "operatorAcceptance": "unverified",
        "truth": {
            "productionImplementation": False,
            "accepted": False,
            "activated": False,
            "released": False,
        },
        "claimBoundary": (
            "observed execution only; no independent acceptance, selected-host "
            "approval, activation, promotion, or release authority"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(args.output)
    print(json.dumps(projection, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)

write(
    "scripts/test_hepta_objective_evidence_project.py",
    r'''from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hepta-objective-evidence-project.py"
SOURCE = "1" * 40
TREE = "2" * 40
LOG = "3" * 64


def candidate(kind: str, exit_code: int = 0) -> dict:
    return {
        "kind": kind,
        "clean": True,
        "checks": [
            {
                "name": "test",
                "status": "completed",
                "exitCode": exit_code,
                "logSha256": LOG,
            }
        ],
    }


class EvidenceProjectionTest(unittest.TestCase):
    def run_projection(
        self, exact: dict | None, target: dict | None
    ) -> tuple[subprocess.CompletedProcess[str], dict | None]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = [
                sys.executable,
                str(SCRIPT),
                "--source-commit",
                SOURCE,
                "--source-tree",
                TREE,
                "--output",
                str(root / "projection.json"),
            ]
            if exact is not None:
                (root / "exact.json").write_text(json.dumps(exact), encoding="utf-8")
                argv += ["--exact-execution", str(root / "exact.json")]
            if target is not None:
                (root / "target.json").write_text(json.dumps(target), encoding="utf-8")
                argv += ["--target-measurement", str(root / "target.json")]
            completed = subprocess.run(argv, text=True, capture_output=True)
            output = root / "projection.json"
            return completed, json.loads(output.read_text()) if output.exists() else None

    def test_projects_passes_without_promoting_acceptance(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "runId": "17",
            "runAttempt": "1",
            "workflowCommit": "4" * 40,
            "candidates": [candidate("source-head"), candidate("synthetic-merge")],
            "checksPassed": True,
            "errors": [],
        }
        target = {
            "schema": "hepta.objective-target-host-evidence.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "hostProfileId": "ci-host",
            "measurements": [{"path": "ordinary"}],
        }
        completed, value = self.run_projection(exact, target)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        assert value is not None
        self.assertEqual(value["exactExecution"]["sourceHeadQualification"], "passed")
        self.assertEqual(
            value["exactExecution"]["syntheticMergeQualification"], "passed"
        )
        self.assertTrue(value["targetHostMeasurement"]["measurementObserved"])
        self.assertFalse(
            value["targetHostMeasurement"]["selectedDeploymentHostAccepted"]
        )
        self.assertEqual(
            value["truth"],
            {
                "productionImplementation": False,
                "accepted": False,
                "activated": False,
                "released": False,
            },
        )

    def test_incomplete_candidate_is_failed_not_passed(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": SOURCE,
            "sourceTree": TREE,
            "candidates": [candidate("source-head", 1)],
            "checksPassed": False,
            "errors": ["observed failure"],
        }
        completed, value = self.run_projection(exact, None)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        assert value is not None
        self.assertEqual(value["exactExecution"]["sourceHeadQualification"], "failed")
        self.assertEqual(
            value["exactExecution"]["syntheticMergeQualification"], "failed"
        )
        self.assertFalse(value["exactExecution"]["checksPassed"])

    def test_source_identity_mismatch_refuses_projection(self) -> None:
        exact = {
            "schema": "hepta.objective.exact-execution.v1",
            "sourceCommit": "9" * 40,
            "sourceTree": TREE,
            "candidates": [],
            "checksPassed": False,
            "errors": [],
        }
        completed, value = self.run_projection(exact, None)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
''',
)

# Exact execution now emits the per-run projection even when checks fail.
p = ".github/workflows/hepta-objective-exact-execution.yml"
replace(
    p,
    '''      - scripts/test_hepta_objective_qualify_exact.py
      - .github/workflows/hepta-objective-exact-execution.yml''',
    '''      - scripts/test_hepta_objective_qualify_exact.py
      - scripts/hepta-objective-evidence-project.py
      - scripts/test_hepta_objective_evidence_project.py
      - .github/workflows/hepta-objective-exact-execution.yml''',
)
replace(
    p,
    '''      - name: Qualify source and deterministic merge without source writes
        shell: bash''',
    '''      - name: Test evidence projection semantics
        shell: bash
        run: python3 -m unittest -v scripts.test_hepta_objective_evidence_project
      - name: Qualify source and deterministic merge without source writes
        shell: bash''',
)
replace(
    p,
    '''      - name: Preserve observed failures and partial execution as evidence
        if: always()''',
    '''      - name: Project the observed execution receipt
        if: always()
        shell: bash
        run: |
          set -euo pipefail
          receipt="$RUNNER_TEMP/objective-exact-evidence/receipt.json"
          if [[ -f "$receipt" ]]; then
            python3 scripts/hepta-objective-evidence-project.py \
              --source-commit "$SOURCE_SHA" \
              --source-tree "$(git rev-parse HEAD^{tree})" \
              --exact-execution "$receipt" \
              --output "$RUNNER_TEMP/objective-exact-evidence/evidence-projection.json"
          fi
      - name: Preserve observed failures and partial execution as evidence
        if: always()''',
)

# Permanent read-only qualification-host measurement. This is intentionally not
# deployment-host acceptance and cannot mutate source.
write(
    ".github/workflows/hepta-objective-target-measurement.yml",
    r'''name: Hepta objective target measurement

on:
  push:
    branches:
      - work/objective-compiler-production-convergence-20260927
    paths:
      - codex-rs/hepta-objective/**
      - codex-rs/hepta-intelligence/**
      - codex-rs/hepta-agentd/**
      - codex-rs/hepta-learning-ledger/**
      - scripts/hepta-objective-target-measure.py
      - scripts/hepta-objective-evidence-project.py
      - scripts/test_hepta_objective_evidence_project.py
      - .github/workflows/hepta-objective-target-measurement.yml
  workflow_dispatch:
    inputs:
      source_commit:
        description: Full immutable source commit; checkout uses this value
        required: true
        type: string

permissions:
  contents: read

env:
  SOURCE_SHA: ${{ inputs.source_commit || github.sha }}

concurrency:
  group: objective-target-measurement-${{ inputs.source_commit || github.sha }}
  cancel-in-progress: false

jobs:
  measure:
    runs-on: macos-15
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Bind immutable qualification host candidate
        shell: bash
        run: |
          set -euo pipefail
          [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          test -z "$(git status --porcelain)"
      - name: Test measurement and evidence recorders
        shell: bash
        run: |
          set -euo pipefail
          python3 scripts/hepta-objective-target-measure.py --self-test
          python3 -m unittest -v scripts.test_hepta_objective_evidence_project
      - name: Measure named qualification host
        shell: bash
        run: |
          set -euo pipefail
          out="$RUNNER_TEMP/objective-target-measurement"
          mkdir -p "$out"
          python3 scripts/hepta-objective-target-measure.py \
            --expected-sha "$SOURCE_SHA" \
            --host-profile-id "github-actions-macos-15-qualification-not-deployment-acceptance" \
            --ordinary-samples 128 \
            --conflict-samples 8 \
            --product-samples 8 \
            --execution-samples 2 \
            --output "$out/measurement.json"
          python3 scripts/hepta-objective-evidence-project.py \
            --source-commit "$SOURCE_SHA" \
            --source-tree "$(git rev-parse HEAD^{tree})" \
            --target-measurement "$out/measurement.json" \
            --output "$out/evidence-projection.json"
      - name: Preserve measurement or observed failure evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: objective-target-measurement-${{ env.SOURCE_SHA }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/objective-target-measurement
          if-no-files-found: warn
          retention-days: 14
      - name: Verify source remained immutable
        if: always()
        shell: bash
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          git diff --check
          git diff --exit-code
          test -z "$(git status --porcelain --untracked-files=no)"
''',
)


print("objective_evidence_edit.py: applied")
