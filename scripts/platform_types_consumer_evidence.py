#!/usr/bin/env python3
"""Bind every required consumer outcome to its log and real executed-test count."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from platform_types_nonempty_tests import executed_tests

EXPECTED_CHECKS = (
    "consumer-map", "canonical-python", "canonical-node", "rejections-python",
    "rejections-node", "manifest-python", "manifest-node", "wire-python", "wire-node",
    "generated-drift", "binding-python", "binding-node", "consumer-compile",
    "manifest-rust", "types-tests", "wire-tests", "ndu-tests", "prompt-producer",
    "prompt-ledger", "topology-consumer", "manifest-owners", "types-lint", "wire-lint",
    "ndu-lint",
)
TEST_CHECKS = frozenset(("manifest-rust", "types-tests", "wire-tests", "ndu-tests",
                         "prompt-producer", "prompt-ledger", "topology-consumer", "manifest-owners"))


def collect_checks(evidence: Path) -> tuple[list[dict], list[str]]:
    errors = []
    checks = []
    try:
        rows = [line.split("\t") for line in (evidence / "results.tsv").read_text().splitlines()]
        if any(len(row) != 3 for row in rows) or tuple(row[0] for row in rows) != EXPECTED_CHECKS:
            raise ValueError("required consumer check names/order differ")
        for name, raw_code, raw_seconds in rows:
            code, seconds = int(raw_code), int(raw_seconds)
            if code < 0 or seconds < 0:
                raise ValueError("negative consumer status or duration")
            log = evidence / (name + ".log")
            raw_log = log.read_bytes()
            row = {"name": name, "exitCode": code, "seconds": seconds,
                   "log": log.name, "logSha256": hashlib.sha256(raw_log).hexdigest()}
            if name in TEST_CHECKS and code == 0:
                try:
                    count = executed_tests(raw_log.decode("utf-8"))
                    count_file = evidence / (name + "-count.json")
                    raw_count = count_file.read_bytes()
                    stated = json.loads(raw_count)
                    if (not isinstance(stated, dict) or set(stated) != {"executedTests"}
                            or type(stated["executedTests"]) is not int
                            or stated["executedTests"] != count):
                        raise ValueError("executed-test count does not match retained log")
                    row.update(executedTests=count, testCountLog=count_file.name,
                               testCountSha256=hashlib.sha256(raw_count).hexdigest())
                except (OSError, UnicodeError, ValueError) as error:
                    errors.append(f"{name}: {error}")
            checks.append(row)
    except (OSError, UnicodeError, ValueError) as error:
        errors.append(str(error))
    return checks, errors


def build_record(root: Path, evidence: Path, initial_head: str,
                 initial_tree: str, initial_status: str) -> dict:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    checks, errors = collect_checks(evidence)
    final_head = git("rev-parse", "HEAD")
    final_tree = git("rev-parse", "HEAD^{tree}")
    unchanged = (initial_head, initial_tree) == (final_head, final_tree)
    clean = not initial_status and not git("status", "--porcelain", "--untracked-files=normal")
    passed = (not errors and tuple(row["name"] for row in checks) == EXPECTED_CHECKS
              and all(row["exitCode"] == 0 for row in checks))
    return {"schema": "hepta.platform-types.consumer-execution.v2",
            "sourceHead": initial_head, "sourceTree": initial_tree,
            "finalSourceHead": final_head, "finalSourceTree": final_tree,
            "sourceUnchanged": unchanged, "cleanWorktree": clean,
            "checksPassed": passed, "qualified": passed and clean and unchanged,
            "checks": checks, "evidenceErrors": errors,
            "productActivation": False, "independentAcceptance": False}


def main() -> int:
    if len(sys.argv) != 6:
        raise SystemExit("usage: platform_types_consumer_evidence.py <root> <evidence> <initial-head> <initial-tree> <initial-status>")
    root, evidence = map(Path, sys.argv[1:3])
    record = build_record(root, evidence, *sys.argv[3:6])
    temporary = evidence / "execution.json.tmp"
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(evidence / "execution.json")
    print(json.dumps({key: record[key] for key in ("sourceHead", "checksPassed", "qualified")}))
    return 0 if record["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
