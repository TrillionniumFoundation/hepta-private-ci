#!/usr/bin/env python3
"""API compatibility and real mutation campaign for control.engineering."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


MUTANTS = (
    (
        "clock-future-skew",
        "control_engineering_v2/governance.py",
        "if future_skew > policy.maximum_future_skew_ns:",
        "if future_skew < policy.maximum_future_skew_ns:",
    ),
    (
        "quality-threshold-direction",
        "control_engineering_v2/quality_gate.py",
        "if value < minimum:",
        "if value > minimum:",
    ),
    (
        "provider-payload-digest",
        "control_engineering_v2/external_runtime.py",
        'if semantic_digest(response_payload) != decoded["payloadDigest"]:',
        'if semantic_digest(response_payload) == decoded["payloadDigest"]:',
    ),
    (
        "review-acceptance-polarity",
        "control_engineering_v2/release_qualification.py",
        "if review.accepted is not True:",
        "if review.accepted is True:",
    ),
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _public_symbols(path: Path) -> list[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = []
    for node in module.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                values.append(node.name)
    return sorted(values)


def verify_api(root: Path, snapshot_path: Path) -> dict[str, object]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict) or snapshot.get("schema") != "hepta.control-engineering-api.v1":
        raise ValueError("invalid API snapshot")
    modules = snapshot.get("modules")
    if not isinstance(modules, dict) or not modules:
        raise ValueError("invalid API snapshot modules")
    observed: dict[str, list[str]] = {}
    for relative, expected in sorted(modules.items()):
        if not isinstance(relative, str) or not isinstance(expected, list):
            raise ValueError("invalid API snapshot entry")
        path = root / relative
        actual = _public_symbols(path)
        if actual != expected:
            raise RuntimeError(
                f"public API drift for {relative}: expected {expected!r}, observed {actual!r}"
            )
        observed[relative] = actual
    return {
        "schema": "hepta.control-engineering-api-check.v1",
        "snapshotDigest": _digest(snapshot_path),
        "moduleCount": len(observed),
        "symbolCount": sum(len(values) for values in observed.values()),
        "passed": True,
    }


def _run_tests(root: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(root)
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-v",
            "-s",
            str(root),
            "-p",
            "test_production_convergence.py",
        ],
        cwd=root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )


def run_mutation_campaign(root: Path) -> dict[str, object]:
    baseline = _run_tests(root)
    if baseline.returncode != 0:
        raise RuntimeError("baseline tests failed:\n" + baseline.stdout[-8000:])
    rows = []
    killed = 0
    with tempfile.TemporaryDirectory(prefix="hepta-control-mutants-") as temporary:
        workspace = Path(temporary)
        for name, relative, before, after in MUTANTS:
            candidate = workspace / name
            if candidate.exists():
                shutil.rmtree(candidate)
            shutil.copytree(
                root,
                candidate,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".coverage"),
            )
            path = candidate / relative
            text = path.read_text(encoding="utf-8")
            if text.count(before) != 1:
                raise RuntimeError(f"mutation anchor is not unique: {name}")
            path.write_text(text.replace(before, after), encoding="utf-8")
            result = _run_tests(candidate)
            mutant_killed = result.returncode != 0
            killed += int(mutant_killed)
            rows.append(
                {
                    "mutant": name,
                    "killed": mutant_killed,
                    "exitCode": result.returncode,
                    "outputDigest": hashlib.sha256(result.stdout.encode()).hexdigest(),
                }
            )
    score_q16 = killed * 65_536 // len(rows)
    report = {
        "schema": "hepta.control-engineering-mutation-campaign.v1",
        "baselinePassed": True,
        "mutants": rows,
        "killed": killed,
        "total": len(rows),
        "scoreQ16": score_q16,
        "passed": killed == len(rows),
    }
    if not report["passed"]:
        survivors = ", ".join(row["mutant"] for row in rows if not row["killed"])
        raise RuntimeError("surviving mutants: " + survivors)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("api", "mutation", "all"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--api-snapshot", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    reports: dict[str, object] = {
        "schema": "hepta.control-engineering-quality-campaign.v1"
    }
    if args.command in {"api", "all"}:
        if args.api_snapshot is None:
            parser.error("--api-snapshot is required for API verification")
        reports["api"] = verify_api(root, args.api_snapshot.resolve())
    if args.command in {"mutation", "all"}:
        reports["mutation"] = run_mutation_campaign(root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
