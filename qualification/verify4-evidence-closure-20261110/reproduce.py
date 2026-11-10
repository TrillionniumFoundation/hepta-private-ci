"""Reproduce bounded VERIFY engineering evidence; never qualifies field benefit."""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "experiments/verification_cell_verify1"


def sources():
    return {
        path.relative_to(ROOT).as_posix(): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "ast_sha256": hashlib.sha256(
                ast.dump(
                    ast.parse(path.read_text(encoding="utf-8")),
                    include_attributes=False,
                ).encode()
            ).hexdigest(),
        }
        for path in sorted(PACKAGE.glob("*.py"))
    }


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = sources()
    records = []
    commands = (
        (
            "tests",
            [
                sys.executable,
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                "experiments/verification_cell_verify1",
                "-t",
                ".",
                "-v",
            ],
        ),
        (
            "sqlite",
            [
                sys.executable,
                "-B",
                "-m",
                "experiments.verification_cell_verify1.experiment",
                "--output",
                str(output / "sqlite"),
                "--groups",
                "3",
            ],
        ),
        (
            "dispatch",
            [
                sys.executable,
                "-B",
                "-m",
                "experiments.verification_cell_verify1.dispatch_smoke",
                "--output",
                str(output / "dispatch"),
            ],
        ),
    )
    for name, command in commands:
        started = datetime.now(timezone.utc).isoformat()
        timer = time.perf_counter()
        with (output / (name + ".log")).open("wb") as stream:
            completed = subprocess.run(
                command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT
            )
        records.append(
            dict(
                name=name,
                command=command,
                started_at_utc=started,
                elapsed_wall_seconds=time.perf_counter() - timer,
                exit_code=completed.returncode,
                log_sha256=hashlib.sha256(
                    (output / (name + ".log")).read_bytes()
                ).hexdigest(),
            )
        )
    after = sources()
    source_unchanged = before == after
    log = (output / "tests.log").read_text(encoding="utf-8", errors="replace")
    counts = re.findall(r"Ran (\d+) tests? in", log)
    skipped = re.findall(r"skipped=(\d+)", log)
    row_path = output / "sqlite/rows.jsonl"
    sqlite_path = output / "sqlite/result.json"
    sqlite_result = json.loads(sqlite_path.read_text()) if sqlite_path.exists() else {}
    dispatch_path = output / "dispatch/RESULT.json"
    dispatch = json.loads(dispatch_path.read_text()) if dispatch_path.exists() else None
    result = dict(
        schema="hepta.verify4.engineering.v1",
        upstream_base="a2cd828aad47c56ac8c01dc2e423454eca7eafae",
        treatment_source="1609a21e5113440bab9de75ccd2afc233e29eec0",
        evidence_class="controlled_engineering_fixtures",
        python=sys.version,
        platform=platform.platform(),
        records=records,
        executed_source=before,
        source_unchanged_during_execution=source_unchanged,
        tests_run=int(counts[-1]) if counts else None,
        tests_skipped=int(skipped[-1]) if skipped else 0,
        sqlite_rows=len(row_path.read_text().splitlines())
        if row_path.exists()
        else None,
        sqlite_confirmation_rows=sqlite_result.get("observed_confirmation_rows"),
        sqlite_planned_confirmation_rows=sqlite_result.get("planned_confirmation_rows"),
        dispatch_scenarios=len(dispatch["rows"]) if dispatch else None,
        actual_dispatch_subprocesses=len(dispatch["subprocess_records"])
        if dispatch
        else None,
        engineering_commands_passed=source_unchanged
        and all(row["exit_code"] == 0 for row in records),
        new_independent_real_tasks=0,
        full_physical_cost_complete=False,
        full_repository_checks_complete=False,
        scientific_admission="HOLD",
        production_authority="NONE",
    )
    (output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in ("executed_source", "records")
            },
            indent=2,
        )
    )
    return 0 if result["engineering_commands_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", required=True, help="new evidence directory; existing paths refuse"
    )
    raise SystemExit(run(parser.parse_args().output))
