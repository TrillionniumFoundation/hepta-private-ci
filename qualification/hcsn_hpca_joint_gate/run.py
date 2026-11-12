"""Run all four research changes on one explicit source assembly.

Earlier per-branch test receipts are not inputs to this gate. This command
executes the declared checks again and retains each original output stream.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    manifest_path = Path(__file__).with_name("MANIFEST.json")
    original_manifest = manifest_path.read_bytes()
    runner_before = Path(__file__).read_bytes()
    manifest = json.loads(original_manifest)
    before = {}
    for record in manifest["sources"]:
        path = root / record["path"]
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != record["sha256"]:
            raise ValueError("joint source differs: " + record["path"])
        before[record["path"]] = actual
    commands = [
        (
            "hcsn-spatial-phase",
            [
                "-B",
                "-m",
                "unittest",
                "qualification.hcsn_boundary_audit.test_spatial_generator",
                "qualification.hcsn_boundary_audit.test_refractory_transport",
                "qualification.hcsn_boundary_audit.test_phase_delay_oracle",
                "-v",
            ],
        ),
        (
            "c2-terminal",
            [
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                "qualification/hcsn_differentiable/c2_successor_v1",
                "-p",
                "test_terminal*.py",
                "-v",
            ],
        ),
        (
            "hpca-normal",
            [
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                "qualification/hpca-neuroscience-20261110",
                "-p",
                "test_chat_evidence_audit.py",
                "-v",
            ],
        ),
        (
            "hpca-optimized",
            [
                "-B",
                "-O",
                "-m",
                "unittest",
                "discover",
                "-s",
                "qualification/hpca-neuroscience-20261110",
                "-p",
                "test_chat_evidence_audit.py",
                "-v",
            ],
        ),
        (
            "spatial-probe",
            [
                "-B",
                "-m",
                "qualification.hcsn_boundary_audit.probe_spatial_generator",
                "--output",
                str(output / "spatial.json"),
            ],
        ),
        (
            "phase-probe",
            [
                "-B",
                "-m",
                "qualification.hcsn_boundary_audit.probe_refractory_transport",
                str(output / "phase.json"),
            ],
        ),
    ]
    results = []
    expected_tests = {
        "hcsn-spatial-phase": 19,
        "c2-terminal": 46,
        "hpca-normal": 15,
        "hpca-optimized": 15,
    }
    for name, arguments in commands:
        wall = time.perf_counter()
        command = [sys.executable, *arguments]
        with (
            (output / f"{name}.stdout").open("xb") as stdout,
            (output / f"{name}.stderr").open("xb") as stderr,
        ):
            try:
                child = subprocess.run(
                    command,
                    cwd=root,
                    stdout=stdout,
                    stderr=stderr,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    timeout=600,
                    check=False,
                )
                code, status = child.returncode, "completed"
            except subprocess.TimeoutExpired:
                code, status = None, "timed_out"
        tests = None
        coverage_complete = True
        if name in expected_tests:
            raw = (output / f"{name}.stderr").read_text()
            matches = re.findall(r"^Ran (\d+) tests? in ", raw, re.MULTILINE)
            tests = int(matches[-1]) if matches else None
            coverage_complete = tests == expected_tests[name] and raw.rstrip().endswith(
                "\nOK"
            )
        results.append(
            dict(
                name=name,
                command=command,
                returncode=code,
                status=status,
                tests=tests,
                complete_unskipped_coverage=coverage_complete,
                wall_seconds=time.perf_counter() - wall,
            )
        )
    after = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in before
    }
    unchanged = (
        before == after
        and original_manifest == manifest_path.read_bytes()
        and runner_before == Path(__file__).read_bytes()
    )
    passed = unchanged and all(
        row["returncode"] == 0 and row["complete_unskipped_coverage"] for row in results
    )
    report = dict(
        schema="hcsn-hpca-joint-check-result-v1",
        status="PASS" if passed else "HOLD",
        manifest_sha256=hashlib.sha256(original_manifest).hexdigest(),
        runtime=platform.python_version(),
        runner_sha256=hashlib.sha256(runner_before).hexdigest(),
        sources_unchanged=unchanged,
        source_sha256=before,
        commands=results,
        source_assembly_only=True,
        full_hcsn_numerical_qualification=False,
        independent_complete_c2_replay=False,
        hpca_independent_future=False,
        production_qualified=False,
    )
    with (output / "RESULT.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "commands": results,
                "sources_unchanged": unchanged,
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
